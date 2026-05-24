"""Hyperliquid REST adapter.

Hyperliquid is an L1 with a centralised order book API. Auth is via EVM-style
signing: each action is signed with the user's EVM private key. Phase 5 ships
mocked HTTP only; real signature verification by HL is exercised in Phase 7.

Phase 5 simplification: ``place_order`` ships a structured payload with an
``eth_account``-generated signature over ``f"{address}{nonce_ms}"``. We do NOT
exercise HL's exact EIP-712 type hash here — that's calibrated in Phase 7 against
real testnet responses. The shape of the signed envelope (action / nonce /
signature) matches HL's wire format so the OMS code paths can be exercised end
to end with mocked HTTP.
"""

from __future__ import annotations

import time
from typing import Any, cast

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

from app.backtest.orders import Order
from app.backtest.state import Product
from app.exchanges.errors import AuthFailed, Rejected
from app.exchanges.types import (
    Balance,
    ExchangePosition,
    OrderReceipt,
    OrderStatus,
)
from app.market_data._http import RetryingFetcher
from app.profile.params import ProfileParams

_MS_PER_SECOND = 1000
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_BAD_REQUEST = 400
_DEFAULT_TIMEOUT_S = 10.0


class HyperliquidExchange:
    """Hyperliquid REST adapter (perp-only, USDC-denominated).

    Covers EVM-signed action submission and the minimum endpoints needed by
    the OMS: ``fetch_balance``, ``place_order``, ``fetch_positions``, and
    ``fetch_mark_price``. ``fetch_order`` and ``cancel_order`` remain stubs
    until Phase 7 testnet validation.
    """

    name = "hyperliquid"

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        params: ProfileParams,
        wallet_private_key: str,
        base_url: str,
    ) -> None:
        self._fetcher = fetcher
        self._params = params
        # Account.from_key is sync and deterministic — derives the address +
        # signing key from the hex private key. We keep the Account on the
        # instance so each request reuses the same signer.
        self._account = Account.from_key(wallet_private_key)
        self._base = base_url.rstrip("/")

    def _address(self) -> str:
        return cast("str", self._account.address)

    def _sign_message(self, message: str) -> str:
        """Sign ``message`` with the wallet key, return the hex signature.

        Uses ``encode_defunct`` (EIP-191 personal_sign) rather than HL's full
        EIP-712 type hash — Phase 5 only needs the envelope shape to be
        correct so the OMS plumbing can be exercised. Real HL signature
        verification is calibrated in Phase 7.
        """
        signed = self._account.sign_message(encode_defunct(text=message))
        return cast("str", signed.signature.hex())

    async def _info(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST a query to ``/info``.

        ``/info`` is the public read endpoint — no signing required. We route
        through the shared ``RetryingFetcher`` because read failures are safe
        to retry (idempotent).
        """
        url = f"{self._base}/info"
        return cast(
            "dict[str, Any]", await self._fetcher.post_json(url, body=body)
        )

    async def fetch_balance(self, quote_currency: str) -> Balance:
        # quote_currency is accepted for protocol parity; HL clearinghouse is
        # USDC-denominated only, so any other request would return zero.
        del quote_currency
        body = await self._info(
            {"type": "clearinghouseState", "user": self._address()}
        )
        withdrawable = float(body.get("withdrawable", "0"))
        return Balance(
            venue=self.name,
            quote_currency="USDC",
            free=withdrawable,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        body = await self._info(
            {"type": "clearinghouseState", "user": self._address()}
        )
        positions: list[ExchangePosition] = []
        for asset_pos in body.get("assetPositions", []):
            pos = asset_pos.get("position", {})
            sz = float(pos.get("szi", "0"))
            if sz == 0:
                continue
            entry_px = float(pos.get("entryPx", "0"))
            positions.append(
                ExchangePosition(
                    venue=self.name,
                    symbol=pos["coin"],
                    product="perp",
                    qty_base=sz,
                    avg_entry_px=entry_px,
                    # Phase 5: mark_px is filled from entryPx because the
                    # clearinghouseState response doesn't carry a separate
                    # mark. Phase 7 testnet validation will source mark from
                    # the allMids endpoint at reconciliation time.
                    mark_px=entry_px,
                    unrealized_pnl_quote=float(pos.get("unrealizedPnl", "0")),
                )
            )
        return tuple(positions)

    async def place_order(self, order: Order) -> OrderReceipt:
        """Submit ``order`` via Hyperliquid ``POST /exchange``.

        Uses a fresh ``httpx.AsyncClient`` rather than the shared
        ``RetryingFetcher`` because order submission must never silently
        retry on Rejected / AuthFailed responses — a hidden retry would
        risk a double fill.

        Phase 5 simplified payload — real HL action signing (EIP-712 with
        HL's exact type hash) is calibrated in Phase 7 against testnet.
        """
        action: dict[str, Any] = {
            "type": "order",
            "orders": [
                {
                    "coin": order.symbol,
                    "is_buy": order.side == "buy",
                    "sz": order.qty_base,
                    "limit_px": order.limit_px if order.limit_px else 0.0,
                    "order_type": (
                        {"limit": {"tif": "Gtc"}}
                        if order.order_type == "limit"
                        else {"trigger": {"isMarket": True}}
                    ),
                    "reduce_only": False,
                }
            ],
            "grouping": "na",
        }
        nonce_ms = int(time.time() * _MS_PER_SECOND)
        signature = self._sign_message(f"{self._address()}{nonce_ms}")
        payload = {
            "action": action,
            "nonce": nonce_ms,
            "signature": signature,
        }
        url = f"{self._base}/exchange"
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(url, json=payload, timeout=_DEFAULT_TIMEOUT_S)
        except httpx.RequestError as e:
            raise RuntimeError(f"hyperliquid place_order: {e}") from e
        if resp.status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
            raise AuthFailed(f"hyperliquid place_order: {resp.text}")
        if resp.status_code >= _HTTP_BAD_REQUEST:
            raise Rejected(
                f"hyperliquid place_order: {resp.status_code} {resp.text}"
            )
        body = resp.json()
        if body.get("status") != "ok":
            raise Rejected(f"hyperliquid: {body}")
        # HL returns either ``resting`` (limit on book) or ``filled`` (market /
        # marketable limit). Both shapes carry the same ``oid`` field.
        status = body["response"]["data"]["statuses"][0]
        leg = status.get("resting") or status.get("filled") or {}
        oid = leg.get("oid")
        if oid is None:
            raise Rejected(f"hyperliquid: missing oid in {body}")
        return OrderReceipt(
            order_id=str(oid),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=nonce_ms,
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        # Phase 5: stub. Real HL ``POST /info {"type":"orderStatus", ...}``
        # is exercised in Phase 7 testnet validation.
        return OrderStatus(
            order_id=order_id,
            status="pending",
            fill_px=None,
            filled_qty_base=0.0,
            fee_quote=0.0,
            raw={},
        )

    async def cancel_order(self, order_id: str) -> None:
        # Phase 5: stub. Real HL cancel requires the coin + oid signed under
        # the same EIP-712 envelope as ``place_order``. Phase 7.
        del order_id

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        del product  # HL is perp-only; product is accepted for protocol parity.
        body = await self._info({"type": "allMids"})
        if symbol in body:
            return float(body[symbol])
        raise KeyError(f"no mark for {symbol} on hyperliquid")
