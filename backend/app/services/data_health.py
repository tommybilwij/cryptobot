"""DataHealthService — gap detection + freshness checks + event logging."""

from __future__ import annotations

from pathlib import Path

import polars as pl
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import DataType
from app.models.data_health_event import DataHealthEvent

ONE_MINUTE_MS = 60_000
_MIN_ROWS_FOR_GAP_DETECTION = 2


class DataHealthService:
    def __init__(self, *, session: AsyncSession, parquet_root: Path) -> None:
        self._session = session
        self._root = parquet_root

    def detect_kline_gaps(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> list[tuple[int, int]]:
        path = (
            self._root
            / exchange
            / symbol
            / DataType.KLINE_1M.value
            / f"{year:04d}"
            / f"{month:02d}.parquet"
        )
        if not path.exists():
            return []
        df = pl.read_parquet(path).sort("ts_ms")
        if df.height < _MIN_ROWS_FOR_GAP_DETECTION:
            return []
        ts = df["ts_ms"].to_list()
        gaps: list[tuple[int, int]] = []
        for i in range(1, len(ts)):
            expected = ts[i - 1] + ONE_MINUTE_MS
            if ts[i] > expected:
                gap_start = expected
                gap_end = ts[i] - ONE_MINUTE_MS
                gaps.append((gap_start, gap_end))
        return gaps

    async def log_event(
        self,
        *,
        event_type: str,
        exchange: str,
        symbol: str | None = None,
        data_type: str | None = None,
        severity: str = "warning",
        description: str | None = None,
        details: dict[str, object] | None = None,
    ) -> DataHealthEvent:
        event = DataHealthEvent(
            event_type=event_type,
            exchange=exchange,
            symbol=symbol,
            data_type=data_type,
            severity=severity,
            description=description,
            details=details or {},
        )
        self._session.add(event)
        await self._session.flush()
        return event
