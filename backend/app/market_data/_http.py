"""Shared HTTP fetcher with exponential-backoff retry on transient failures.

Used by all three downloaders. 404 is treated as a permanent miss
(FileNotFoundError); 5xx and 429 retry with exponential backoff; everything
else raises RuntimeError.
"""

from __future__ import annotations

import asyncio
from typing import cast

from httpx import AsyncClient, HTTPStatusError, RequestError

_HTTP_OK = 200
_HTTP_CREATED = 201
_HTTP_NOT_FOUND = 404


class RetryingFetcher:
    """Wraps httpx.AsyncClient with retry semantics tuned for exchange archives."""

    def __init__(
        self,
        *,
        client: AsyncClient,
        max_retries: int = 5,
        base_backoff_s: float = 0.5,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._base = base_backoff_s

    async def get_bytes(self, url: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(url, timeout=30.0)
                if resp.status_code == _HTTP_NOT_FOUND:
                    raise FileNotFoundError(url)
                if resp.status_code == _HTTP_OK:
                    return resp.content
                # 429 / 5xx → retry
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code} on {url}: {resp.text[:200]}"
                )
            except RequestError as e:
                last_exc = e
            except HTTPStatusError as e:
                last_exc = e

            if attempt < self._max_retries:
                await asyncio.sleep(self._base * (2**attempt))
        raise RuntimeError(f"max retries exceeded for {url}: {last_exc}")

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(
                    url, params=params, headers=headers, timeout=30.0
                )
                if resp.status_code == _HTTP_NOT_FOUND:
                    raise FileNotFoundError(url)
                if resp.status_code == _HTTP_OK:
                    return cast("dict[str, object] | list[object]", resp.json())
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code} on {url}: {resp.text[:200]}"
                )
            except RequestError as e:
                last_exc = e
            except HTTPStatusError as e:
                last_exc = e

            if attempt < self._max_retries:
                await asyncio.sleep(self._base * (2**attempt))
        raise RuntimeError(f"max retries exceeded for {url}: {last_exc}")

    async def post_json(
        self,
        url: str,
        *,
        body: dict[str, object],
        headers: dict[str, str] | None = None,
    ) -> dict[str, object] | list[object]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(
                    url, json=body, headers=headers, timeout=30.0
                )
                if resp.status_code in (_HTTP_OK, _HTTP_CREATED):
                    return cast("dict[str, object] | list[object]", resp.json())
                last_exc = RuntimeError(
                    f"HTTP {resp.status_code} on POST {url}: {resp.text[:200]}"
                )
            except RequestError as e:
                last_exc = e
            except HTTPStatusError as e:
                last_exc = e

            if attempt < self._max_retries:
                await asyncio.sleep(self._base * (2**attempt))
        raise RuntimeError(f"max retries exceeded for POST {url}: {last_exc}")
