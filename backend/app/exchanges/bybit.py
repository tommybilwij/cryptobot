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
from typing import Any, Literal, cast

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
        body = cast("dict[str, Any]", await self._fetcher.get_json(url, headers=headers))
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
        """Return open perp positions via ``GET /v5/position/list``.

        Queries the ``linear`` category with ``settleCoin=USDT`` (Bybit V5
        requires either symbol or settleCoin); zero-size rows are filtered.
        Spot holdings are reported as ``Balance`` rows by ``fetch_balance``,
        not as positions.
        """
        ts_ms = str(int(time.time() * _MS_PER_SECOND))
        query = "category=linear&settleCoin=USDT"
        url = f"{self._base}/v5/position/list?{query}"
        headers = self._headers(ts_ms, query)
        body = cast("dict[str, Any]", await self._fetcher.get_json(url, headers=headers))
        self._check_response(body)
        positions: list[ExchangePosition] = []
        for entry in body.get("result", {}).get("list", []):
            qty = float(entry.get("size", "0"))
            if qty == 0.0:
                continue
            # Bybit V5 reports side ("Buy"/"Sell") + unsigned size; convert to
            # signed qty so downstream consumers see direction in a single field.
            signed_qty = qty if entry.get("side") == "Buy" else -qty
            positions.append(
                ExchangePosition(
                    venue=self.name,
                    symbol=entry["symbol"],
                    product="perp",
                    qty_base=signed_qty,
                    avg_entry_px=float(entry.get("avgPrice", "0")),
                    mark_px=float(entry.get("markPrice", "0")),
                    unrealized_pnl_quote=float(entry.get("unrealisedPnl", "0")),
                )
            )
        return tuple(positions)

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
            raise Rejected(f"bybit place_order: {resp.status_code} {resp.text}")
        data = resp.json()
        self._check_response(data)
        return OrderReceipt(
            order_id=str(data["result"]["orderId"]),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=int(ts_ms),
        )

    async def fetch_order(self, order_id: str, symbol: str | None = None) -> OrderStatus:
        """Query an order via ``GET /v5/order/realtime`` in the linear category.

        ``symbol`` is accepted for Protocol parity but not required by
        Bybit's realtime endpoint — ``orderId`` alone is sufficient. The
        status_map normalises Bybit's enum to ``_OrderStatusLiteral``.
        """
        del symbol
        ts_ms = str(int(time.time() * _MS_PER_SECOND))
        query = f"category=linear&orderId={order_id}"
        url = f"{self._base}/v5/order/realtime?{query}"
        headers = self._headers(ts_ms, query)
        body = cast("dict[str, Any]", await self._fetcher.get_json(url, headers=headers))
        self._check_response(body)
        rows = body.get("result", {}).get("list", [])
        if not rows:
            return OrderStatus(
                order_id=order_id,
                status="pending",
                fill_px=None,
                filled_qty_base=0.0,
                fee_quote=0.0,
                raw=body,
            )
        row = rows[0]
        status_map: dict[
            str,
            Literal["pending", "filled", "partially_filled", "cancelled", "rejected"],
        ] = {
            "Filled": "filled",
            "PartiallyFilled": "partially_filled",
            "Cancelled": "cancelled",
            "Rejected": "rejected",
            "New": "pending",
        }
        s = status_map.get(row.get("orderStatus", "New"), "pending")
        filled = float(row.get("cumExecQty", "0"))
        cum_value = float(row.get("cumExecValue", "0"))
        fill_px = cum_value / filled if filled > 0 else None
        return OrderStatus(
            order_id=order_id,
            status=s,
            fill_px=fill_px,
            filled_qty_base=filled,
            fee_quote=float(row.get("cumExecFee", "0")),
            raw=row,
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def amend_order(
        self,
        order_id: str,
        *,
        new_qty: float | None = None,
        new_limit_px: float | None = None,
    ) -> OrderStatus:
        """Amend via Bybit V5 ``POST /v5/order/amend``.

        Bybit's amend is a true in-place mutation (no cancel + replace), so
        the returned ``orderId`` matches the input. We POST through a fresh
        ``httpx.AsyncClient`` for the same double-fill safety as
        ``place_order``. Phase 11 returns a pending stub; the OMS polls
        ``fetch_order`` afterwards for live fill data.
        """
        body_obj: dict[str, Any] = {
            "category": "linear",
            "orderId": order_id,
        }
        if new_qty is not None:
            body_obj["qty"] = str(new_qty)
        if new_limit_px is not None:
            body_obj["price"] = str(new_limit_px)
        payload = json.dumps(body_obj, separators=(",", ":"))
        ts_ms = str(int(time.time() * _MS_PER_SECOND))
        url = f"{self._base}/v5/order/amend"
        headers = {**self._headers(ts_ms, payload), "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(
                    url, content=payload, headers=headers, timeout=_DEFAULT_TIMEOUT_S
                )
        except httpx.RequestError as e:
            raise RuntimeError(f"bybit amend_order: {e}") from e
        if resp.status_code == _HTTP_UNAUTHORIZED:
            raise AuthFailed(f"bybit amend_order: {resp.text}")
        if resp.status_code >= _HTTP_BAD_REQUEST:
            raise Rejected(f"bybit amend_order: {resp.status_code} {resp.text}")
        data = resp.json()
        self._check_response(data)
        new_oid = str(data.get("result", {}).get("orderId", order_id))
        return OrderStatus(
            order_id=new_oid,
            status="pending",
            fill_px=None,
            filled_qty_base=0.0,
            fee_quote=0.0,
            raw=data,
        )

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        category = "linear" if product == "perp" else "spot"
        url = f"{self._base}/v5/market/tickers?category={category}&symbol={symbol}"
        body = cast("dict[str, Any]", await self._fetcher.get_json(url))
        self._check_response(body)
        return float(body["result"]["list"][0]["lastPrice"])

    async def fetch_funding_rate(self, symbol: str) -> float | None:
        """Read most recent funding rate via ``/v5/market/funding/history``.

        Public endpoint (no signing). Returns ``None`` if the venue is
        unreachable or the symbol is unknown — callers treat missing funding
        as a soft signal absence, not a hard failure.
        """
        url = f"{self._base}/v5/market/funding/history?category=linear&symbol={symbol}&limit=1"
        try:
            body = cast("dict[str, Any]", await self._fetcher.get_json(url))
        except RuntimeError:
            return None
        if int(body.get("retCode", -1)) != _OK_RET_CODE:
            return None
        rows = body.get("result", {}).get("list", [])
        if not rows:
            return None
        return float(rows[0].get("fundingRate", "0"))
