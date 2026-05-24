"""Binance REST adapter (spot + USDS-margined perp).

Auth: HMAC SHA256 over the query string, header ``X-MBX-APIKEY``.
Phase 5 ships with mocked HTTP only; real testnet integration is Phase 7.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse
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

_RECV_WINDOW_MS = 5000
_AUTH_FAIL_CODES: set[int] = {401, 403}
_REJECTED_CODES: set[int] = {400, 422}
_HTTP_OK = 200
_MS_PER_SECOND = 1000
_DEFAULT_TIMEOUT_S = 10.0


class BinanceExchange:
    """Binance spot REST adapter.

    Phase 5 covers the signed-request plumbing (HMAC SHA256, recv-window,
    ``X-MBX-APIKEY``) and the minimum endpoints needed by the OMS:
    ``fetch_balance``, ``place_order``, and ``fetch_mark_price``.
    ``fetch_positions`` and ``fetch_order`` are stubs until Phase 7 testnet
    validation.
    """

    name = "binance"

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

    def _sign(self, params: dict[str, Any]) -> str:
        """Return ``urlencode(params) + "&signature=<hex>"``.

        Binance signs the urlencoded query string with HMAC SHA256 over the
        api secret and appends ``signature=`` as the final query param.
        """
        query = urllib.parse.urlencode(params)
        sig = hmac.new(
            self._api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={sig}"

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self._api_key}

    async def _signed_get(self, path: str, params: dict[str, Any]) -> Any:
        """Send a signed Binance GET.

        Return type is ``Any`` because Binance endpoints return either an
        object (``dict``) or an array (``list``) — e.g. ``/fapi/v2/positionRisk``
        is a JSON array. Callers narrow the type at the use site.
        """
        params = {
            **params,
            "timestamp": int(time.time() * _MS_PER_SECOND),
            "recvWindow": _RECV_WINDOW_MS,
        }
        url = f"{self._base}{path}?{self._sign(params)}"
        try:
            result = await self._fetcher.get_json(url, headers=self._headers())
        except RuntimeError as e:
            self._maybe_raise(e)
            raise
        return result

    async def _signed_post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a signed Binance POST.

        Binance signed POST encodes the signature in the query string and uses
        an empty body. We use a fresh ``httpx.AsyncClient`` so the retry policy
        does not silently swallow auth or rejection responses — a misplaced
        retry on a Rejected order could create double fills.
        """
        params = {
            **params,
            "timestamp": int(time.time() * _MS_PER_SECOND),
            "recvWindow": _RECV_WINDOW_MS,
        }
        url = f"{self._base}{path}?{self._sign(params)}"
        try:
            async with httpx.AsyncClient() as raw:
                resp = await raw.post(
                    url, headers=self._headers(), timeout=_DEFAULT_TIMEOUT_S
                )
        except httpx.RequestError as e:
            raise RuntimeError(f"post {path}: {e}") from e
        if resp.status_code in _AUTH_FAIL_CODES:
            raise AuthFailed(f"binance auth failure on {path}: {resp.text}")
        if resp.status_code in _REJECTED_CODES:
            raise Rejected(f"binance rejected {path}: {resp.text}")
        if resp.status_code != _HTTP_OK:
            raise RuntimeError(f"binance {path}: {resp.status_code} {resp.text}")
        return resp.json()  # type: ignore[no-any-return]

    @staticmethod
    def _maybe_raise(err: RuntimeError) -> None:
        """Translate a fetcher ``RuntimeError`` into typed exchange errors.

        The shared fetcher embeds the HTTP status in its error message
        (``HTTP <code> on <url>: ...``). Translate 401/403 to AuthFailed and
        400/422 to Rejected; anything else stays a RuntimeError.
        """
        msg = str(err)
        for code in _AUTH_FAIL_CODES:
            if f"HTTP {code}" in msg:
                raise AuthFailed(msg) from err
        for code in _REJECTED_CODES:
            if f"HTTP {code}" in msg:
                raise Rejected(msg) from err

    async def fetch_balance(self, quote_currency: str) -> Balance:
        body = await self._signed_get("/api/v3/account", {})
        for entry in body.get("balances", []):
            if entry["asset"] == quote_currency:
                return Balance(
                    venue=self.name,
                    quote_currency=quote_currency,
                    free=float(entry["free"]),
                    locked=float(entry["locked"]),
                )
        return Balance(
            venue=self.name, quote_currency=quote_currency, free=0.0, locked=0.0
        )

    async def fetch_positions(self) -> tuple[ExchangePosition, ...]:
        """Return open perp positions via ``/fapi/v2/positionRisk``.

        Binance returns a JSON array with one row per (symbol, position-side);
        zero-quantity rows are placeholders for symbols the account has ever
        touched and are filtered out. Spot holdings are not included — those
        are reported as ``Balance`` rows by ``fetch_balance``.
        """
        body = await self._signed_get("/fapi/v2/positionRisk", {})
        rows: list[dict[str, Any]] = body if isinstance(body, list) else []
        positions: list[ExchangePosition] = []
        for entry in rows:
            qty = float(entry["positionAmt"])
            if qty == 0.0:
                continue
            positions.append(
                ExchangePosition(
                    venue=self.name,
                    symbol=entry["symbol"],
                    product="perp",
                    qty_base=qty,
                    avg_entry_px=float(entry["entryPrice"]),
                    mark_px=float(entry["markPrice"]),
                    unrealized_pnl_quote=float(entry["unRealizedProfit"]),
                )
            )
        return tuple(positions)

    async def place_order(self, order: Order) -> OrderReceipt:
        params: dict[str, Any] = {
            "symbol": order.symbol,
            "side": order.side.upper(),
            "type": "MARKET" if order.order_type == "market" else "LIMIT",
            "quantity": str(order.qty_base),
        }
        if order.order_type == "limit":
            assert order.limit_px is not None
            params["price"] = str(order.limit_px)
            params["timeInForce"] = "GTC"
        path = "/api/v3/order"
        body = await self._signed_post(path, params)
        return OrderReceipt(
            order_id=str(body["orderId"]),
            venue=self.name,
            symbol=order.symbol,
            submitted_ts_ms=int(
                body.get("transactTime", time.time() * _MS_PER_SECOND)
            ),
        )

    async def fetch_order(
        self, order_id: str, symbol: str | None = None
    ) -> OrderStatus:
        """Query an order via ``GET /api/v3/order``.

        Binance requires ``symbol`` in the query — without it the only safe
        response is a pending stub, because the venue refuses orderId-only
        lookups. The status_map normalises Binance's enum to our
        ``OrderStatus._OrderStatusLiteral``.
        """
        if symbol is None:
            return OrderStatus(
                order_id=order_id,
                status="pending",
                fill_px=None,
                filled_qty_base=0.0,
                fee_quote=0.0,
                raw={},
            )
        body = await self._signed_get(
            "/api/v3/order", {"symbol": symbol, "orderId": int(order_id)}
        )
        status_map: dict[
            str,
            Literal["pending", "filled", "partially_filled", "cancelled", "rejected"],
        ] = {
            "FILLED": "filled",
            "PARTIALLY_FILLED": "partially_filled",
            "CANCELED": "cancelled",
            "REJECTED": "rejected",
            "NEW": "pending",
        }
        s = status_map.get(body.get("status", "NEW"), "pending")
        filled = float(body.get("executedQty", "0"))
        cum_quote = float(body.get("cummulativeQuoteQty", "0"))
        fill_px = cum_quote / filled if filled > 0 else None
        return OrderStatus(
            order_id=order_id,
            status=s,
            fill_px=fill_px,
            filled_qty_base=filled,
            fee_quote=0.0,
            raw=body,
        )

    async def cancel_order(self, order_id: str) -> None:
        return

    async def fetch_mark_price(self, symbol: str, product: Product) -> float:
        body = await self._signed_get("/api/v3/ticker/price", {"symbol": symbol})
        return float(body["price"])

    async def fetch_funding_rate(self, symbol: str) -> float | None:
        """Read ``lastFundingRate`` via the public ``/fapi/v1/premiumIndex``.

        Premium index is unsigned (no API key required). Returns ``None`` if
        the endpoint is unreachable or the symbol is unknown — callers treat
        missing funding as "no signal" rather than a hard failure.
        """
        url = f"{self._base}/fapi/v1/premiumIndex?symbol={symbol}"
        try:
            body = await self._fetcher.get_json(url)
        except RuntimeError:
            return None
        if isinstance(body, dict) and "lastFundingRate" in body:
            return float(cast("str", body["lastFundingRate"]))
        return None
