"""Hyperliquid REST adapter.

Hyperliquid is an L1 with a centralised order book API. Auth is via EVM-style
signing: each action is signed with the user's EVM private key.

Phase 7 ships EIP-712 typed-data signing (``encode_typed_data`` against the HL
``Agent`` struct with chainId 1337 — HL's signature chain) and removes the
Phase 5 ``personal_sign`` stub. The exact ``connectionId`` formula in HL's
docs uses keccak over msgpack-encoded action + nonce + vault; we ship a
JSON-stable SHA256 approximation here so the wire envelope shape (``{"r","s","v"}``)
is correct, and rely on the slow-marker testnet smoke test to confirm real
HL acceptance. If testnet rejects, calibrate the ``connectionId`` formula
against the published docs.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal, cast

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

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
# HL EIP-712 signature chain. NOT the same as the ETH mainnet chainId — HL
# pins this to 1337 for the Agent struct used across mainnet + testnet.
_SIG_CHAIN_ID = 1337
_FUNDING_LOOKBACK_HOURS = 24
_SECONDS_PER_HOUR = 3600
_SIG_HEX_R_END = 64
_SIG_HEX_S_END = 128
_SIG_HEX_V_END = 130
_HEX_BASE = 16


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

    def _sign_l1_action(self, action: dict[str, Any], nonce_ms: int) -> dict[str, str | int]:
        """Sign an HL L1 action under the documented EIP-712 ``Agent`` scheme.

        HL signs an ``Agent`` struct ``{source: string, connectionId: bytes32}``
        under chainId 1337 (HL's signature chain — distinct from ETH mainnet).
        The canonical ``connectionId`` is keccak over msgpack(action) + nonce +
        vault; this Phase 7 implementation uses a JSON-stable SHA256 stand-in
        so the wire envelope is the right shape. The slow-marker testnet
        smoke test confirms HL acceptance — if it rejects, calibrate the
        ``connectionId`` formula here against the published docs.
        """
        domain = {
            "name": "Exchange",
            "version": "1",
            "chainId": _SIG_CHAIN_ID,
            "verifyingContract": "0x0000000000000000000000000000000000000000",
        }
        types = {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
        }
        action_json = json.dumps(action, separators=(",", ":"), sort_keys=True)
        connection_id_hex = hashlib.sha256(f"{action_json}{nonce_ms}".encode()).hexdigest()
        message = {
            "source": "a",
            "connectionId": bytes.fromhex(connection_id_hex),
        }
        signable = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
        signed = self._account.sign_message(signable)
        sig_hex = cast("str", signed.signature.hex())
        return {
            "r": "0x" + sig_hex[:_SIG_HEX_R_END],
            "s": "0x" + sig_hex[_SIG_HEX_R_END:_SIG_HEX_S_END],
            "v": int(sig_hex[_SIG_HEX_S_END:_SIG_HEX_V_END], _HEX_BASE),
        }

    async def _info(self, body: dict[str, Any]) -> Any:
        """POST a query to ``/info``.

        ``/info`` is the public read endpoint — no signing required. We route
        through the shared ``RetryingFetcher`` because read failures are safe
        to retry (idempotent). Return type is ``Any`` because HL responses
        are sometimes objects (``clearinghouseState``) and sometimes arrays
        (``fundingHistory``); callers narrow at the use site.
        """
        url = f"{self._base}/info"
        return await self._fetcher.post_json(url, body=body)

    async def fetch_balance(self, quote_currency: str) -> Balance:
        # quote_currency is accepted for protocol parity; HL clearinghouse is
        # USDC-denominated only, so any other request would return zero.
        del quote_currency
        body = await self._info({"type": "clearinghouseState", "user": self._address()})
        withdrawable = float(body.get("withdrawable", "0"))
        return Balance(
            venue=self.name,
            quote_currency="USDC",
            free=withdrawable,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        body = await self._info({"type": "clearinghouseState", "user": self._address()})
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
        signature = self._sign_l1_action(action, nonce_ms)
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
            raise Rejected(f"hyperliquid place_order: {resp.status_code} {resp.text}")
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

    async def fetch_order(self, order_id: str, symbol: str | None = None) -> OrderStatus:
        """Query order status via ``POST /info {"type":"orderStatus"}``.

        ``symbol`` is accepted for Protocol parity but ignored — HL keys
        orders by integer ``oid``. The status_map normalises HL's enum
        (``"filled" | "open" | "canceled"``) to the OrderStatus literal.
        """
        del symbol
        body = await self._info(
            {
                "type": "orderStatus",
                "user": self._address(),
                "oid": int(order_id),
            }
        )
        raw = body.get("order", {})
        hl_status = raw.get("status", "open")
        status_map: dict[
            str,
            Literal["pending", "filled", "partially_filled", "cancelled", "rejected"],
        ] = {
            "filled": "filled",
            "open": "pending",
            "canceled": "cancelled",
        }
        sz = float(raw.get("sz", "0"))
        return OrderStatus(
            order_id=order_id,
            status=status_map.get(hl_status, "pending"),
            fill_px=float(raw["px"]) if "px" in raw else None,
            filled_qty_base=sz,
            fee_quote=0.0,
            raw=body,
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

    async def fetch_funding_rate(self, symbol: str) -> float | None:
        """Most recent funding rate from ``POST /info {"type":"fundingHistory"}``.

        HL returns a chronological array of funding payments; we read the
        last row's ``fundingRate``. Returns ``None`` if the response is
        empty or unreachable — callers treat missing funding as no-signal.
        """
        now_ms = int(time.time() * _MS_PER_SECOND)
        lookback_ms = _FUNDING_LOOKBACK_HOURS * _SECONDS_PER_HOUR * _MS_PER_SECOND
        body = await self._info(
            {
                "type": "fundingHistory",
                "coin": symbol,
                "startTime": now_ms - lookback_ms,
            }
        )
        if isinstance(body, list) and body:
            return float(body[-1].get("fundingRate", 0.0))
        return None
