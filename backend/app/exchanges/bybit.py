"""Bybit V5 REST adapter (unified margin: spot + perp).

Auth: HMAC SHA256 over ``timestamp + api_key + recv_window + (queryString | body)``,
header ``X-BAPI-SIGN``. Bybit V5 returns 200 OK for application-level errors and
encodes the failure as ``retCode != 0`` in the JSON body — so success must be
gated on the ``retCode`` field, not the HTTP status alone.

Phase 5 ships with mocked HTTP only; real testnet integration is Phase 7.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, cast

import httpx

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

_RECV_WINDOW_MS = "5000"
_AUTH_FAIL_RET_CODES: set[int] = {10003, 10004, 10005, 33004}
_HTTP_UNAUTHORIZED = 401
_HTTP_BAD_REQUEST = 400
_OK_RET_CODE = 0
_MS_PER_SECOND = 1000
_DEFAULT_TIMEOUT_S = 10.0


class BybitExchange:
    """Bybit V5 unified-margin REST adapter.

    Covers the signed-request plumbing (HMAC SHA256 of
    ``ts + api_key + recv_window + payload``, ``X-BAPI-*`` headers) and the
    minimum endpoints needed by the OMS: ``fetch_balance``, ``place_order``,
    and ``fetch_mark_price``. ``fetch_positions`` and ``fetch_order`` remain
    stubs until Phase 7 testnet validation.
    """

    name = "bybit"

    def __init__(
        self,
        *,
        fetcher: RetryingFetcher,
        params: ProfileParams,
        api_key: str,
        api_secret: str,
        base_url: str,
    ) -> None:
        self._fetcher = fetcher
        self._params = params
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = base_url.rstrip("/")

    def _sign(self, ts_ms: str, payload: str) -> str:
        """Return the HMAC SHA256 signature for a Bybit V5 request.

        Bybit signs ``ts_ms + api_key + recv_window + payload`` where the
        payload is the raw query string (GET) or the raw JSON body (POST).
        Spaces and key ordering in the payload must match what is sent on
        the wire — re-serialising would change the signature.
        """
        msg = f"{ts_ms}{self._api_key}{_RECV_WINDOW_MS}{payload}"
        return hmac.new(
            self._api_secret.encode(),
            msg.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, ts_ms: str, payload: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": ts_ms,
            "X-BAPI-RECV-WINDOW": _RECV_WINDOW_MS,
            "X-BAPI-SIGN": self._sign(ts_ms, payload),
        }

    def _check_response(self, body: dict[str, Any]) -> None:
        """Translate a Bybit V5 ``retCode`` into typed exchange errors.

        Bybit returns HTTP 200 with ``retCode != 0`` for application-level
        failures, so the JSON body is the source of truth. The auth-failure
        codes (10003 invalid api key, 10004 signature, 10005 permission,
        33004 expired api key) are escalated to ``AuthFailed`` — those must
        halt trading because retrying would not recover.
        """
        code = int(body.get("retCode", -1))
        if code == _OK_RET_CODE:
            return
        if code in _AUTH_FAIL_RET_CODES:
            raise AuthFailed(f"bybit retCode {code}: {body.get('retMsg')}")
        raise Rejected(f"bybit retCode {code}: {body.get('retMsg')}")

    async def fetch_balance(self, quote_currency: str) -> Balance:
        ts_ms = str(int(time.time() * _MS_PER_SECOND))
        query = "accountType=UNIFIED"
        url = f"{self._base}/v5/account/wallet-balance?{query}"
        headers = self._headers(ts_ms, query)
        body = cast(
            "dict[str, Any]", await self._fetcher.get_json(url, headers=headers)
        )
        self._check_response(body)
        wallet_list = body["result"]["list"]
        if not wallet_list:
            return Balance(
                venue=self.name,
                quote_currency=quote_currency,
                free=0.0,
                locked=0.0,
            )
        for coin in wallet_list[0]["coin"]:
            if coin["coin"] == quote_currency:
                return Balance(
                    venue=self.name,
                    quote_currency=quote_currency,
                    free=float(coin["free"]),
                    locked=float(coin["locked"]),
                )
        return Balance(
            venue=self.name,
            quote_currency=quote_currency,
            free=0.0,
            locked=0.0,
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        # Phase 5: stub. Real implementation needs Bybit's
        # ``GET /v5/position/list`` paginated across categories
        # (linear + spot). Empty tuple is correct for a fresh testnet
        # account; Phase 7 testnet validation will exercise the full path.
        return ()

    async def place_order(self, order: Order) -> OrderReceipt:
        """Submit ``order`` via Bybit V5 ``POST /v5/order/create``.

        Uses a fresh ``httpx.AsyncClient`` rather than the shared
        ``RetryingFetcher`` because order submission must never silently
        retry on Rejected / AuthFailed responses — a hidden retry would
        risk a double fill.
        """
        ts_ms = str(int(time.time() * _MS_PER_SECOND))
        body_obj: dict[str, Any] = {
            "category": "linear" if order.product == "perp" else "spot",
            "symbol": order.symbol,
            "side": order.side.capitalize(),
            "orderType": "Market" if order.order_type == "market" else "Limit",
            "qty": str(order.qty_base),
        }
        if order.order_type == "limit":
            assert order.limit_px is not None
            body_obj["price"] = str(order.limit_px)
            body_obj["timeInForce"] = "GTC"
        # Serialise exactly once: Bybit signs the wire payload byte-for-byte,
        # so we send the same string we hashed.
        payload = json.dumps(body_obj, separators=(",", ":"))
        url = f"{self._base}/v5/order/create"
        headers = {**self._headers(ts_ms, payload), "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(
                    url, content=payload, headers=headers, timeout=_DEFAULT_TIMEOUT_S
                )
        except httpx.RequestError as e:
            raise RuntimeError(f"bybit place_order: {e}") from e
        if resp.status_code == _HTTP_UNAUTHORIZED:
            raise AuthFailed(f"bybit place_order: {resp.text}")
        if resp.status_code >= _HTTP_BAD_REQUEST:
            raise Rejected(
                f"bybit place_order: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        self._check_response(data)
        return OrderReceipt(
            order_id=str(data["result"]["orderId"]),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=int(ts_ms),
        )

    async def fetch_order(self, order_id: str) -> OrderStatus:
        # Phase 5: stub. Real Bybit ``GET /v5/order/realtime`` needs the
        # category (linear|spot) which we'd need to thread through from
        # the OrderReceipt. Phase 7 testnet validation will exercise the
        # full path.
        return OrderStatus(
            order_id=order_id,
            status="pending",
            fill_px=None,
            filled_qty_base=0.0,
            fee_quote=0.0,
            raw={},
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        category = "linear" if product == "perp" else "spot"
        url = (
            f"{self._base}/v5/market/tickers"
            f"?category={category}&symbol={symbol}"
        )
        body = cast("dict[str, Any]", await self._fetcher.get_json(url))
        self._check_response(body)
        return float(body["result"]["list"][0]["lastPrice"])
