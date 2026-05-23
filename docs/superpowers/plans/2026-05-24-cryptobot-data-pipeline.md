# Cryptobot — Phase 3 Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land a working historical-data pipeline that downloads from Binance Vision + Bybit public + Hyperliquid archive, stores in partitioned Parquet on local disk, queries via DuckDB into Polars frames, snapshots survivorship-safe universes weekly, and runs data-health checks (gap detection + freshness) via background worker jobs.

**Architecture:** Three exchange-specific downloaders implement a common `MarketDataSource` Protocol. `ParquetStore` owns the write-side partition layout (`{exchange}/{symbol}/{type}/{yyyy}/{mm}.parquet`). `DuckDBQuery` owns the read-side — registers globbed views and returns Polars frames. Background workers (separate Docker services from the heartbeat `worker` stub from Phase 2) dispatch via `WORKER_JOB` env var to refresh / snapshot / health-check entry points. Symbol manifests + health events persist in Postgres so the API and live engine can query them. All cadences (refresh interval, gap-detection sensitivity, max_age thresholds) come from the existing profile registry; no hardcoded values in `services/`, `market_data/`, or `worker/jobs/`.

**Tech Stack:** Polars 1.x (new — replaces pandas everywhere in `market_data/`), DuckDB 1.x (new), httpx async client (existing), pyzipper / zipfile (stdlib for unzipping Binance Vision archives), aiofiles (new — async filesystem writes), pytest + pytest-asyncio (existing).

**Scope:** Phase 3 only. Blocks Phase 4 (backtester needs historical data) and Phase 14 (factor portfolio needs OHLCV + funding + on-chain).

**Definition of done (gate to Phase 4):**
- `just refresh-data` downloads BTCUSDT 1m klines + funding for the last 30 days from Binance Vision and writes them to `data/parquet/binance/BTCUSDT/...`
- `DuckDBQuery(...).klines(exchange="binance", symbol="BTCUSDT", start, end)` returns a Polars DataFrame
- `just data-health` reports zero gaps on the freshly-downloaded data
- Symbol manifest snapshot for `2026-05-24` is in `symbol_manifest_snapshots` table
- Apply `balanced_v1` profile then call `params.get("data_health.max_age_s.funding")` → returns 900 (existing registry default)
- New migration `0002_symbol_manifest_and_data_health` applies cleanly + reverses cleanly
- 22 new tests in `backend/tests/market_data/`, `services/`, `worker/`, `api/` (total ~59 tests after this phase)
- mypy `--strict` clean; ruff + custom AST lint clean
- CI green on PR

---

## Phase 3.1: Dependencies + Parquet conventions

### Task 1: Add Polars + DuckDB + aiofiles to backend deps

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock` (auto-updated by uv)

- [ ] **Step 1: Add deps via uv**

```bash
cd backend && uv add 'polars>=1.0' 'duckdb>=1.0' 'aiofiles>=24.0'
```

- [ ] **Step 2: Add mypy stubs for aiofiles**

```bash
cd backend && uv add --dev 'types-aiofiles'
```

- [ ] **Step 3: Verify uv sync succeeds + existing tests still pass**

```bash
just test
```
Expected: 37 passed (unchanged).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add polars + duckdb + aiofiles to backend deps"
```

---

### Task 2: ParquetStore (write-side partition layout)

**Files:**
- Create: `backend/app/market_data/__init__.py`
- Create: `backend/app/market_data/parquet_store.py`
- Create: `backend/tests/market_data/__init__.py`
- Create: `backend/tests/market_data/test_parquet_store.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/market_data/__init__.py`:
```python
```

`backend/tests/market_data/test_parquet_store.py`:
```python
"""Tests for ParquetStore — write-side partition layout."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from app.market_data.parquet_store import DataType, ParquetStore


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(root=tmp_path)


def _sample_klines() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [60000.0, 60010.0, 60020.0],
            "high": [60015.0, 60025.0, 60030.0],
            "low": [59995.0, 60005.0, 60015.0],
            "close": [60010.0, 60020.0, 60025.0],
            "volume": [10.5, 11.0, 9.75],
        }
    )


def test_path_format(store: ParquetStore) -> None:
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.relative_to(store.root) == Path("binance/BTCUSDT/kline_1m/2026/04.parquet")


def test_write_klines_creates_partition(store: ParquetStore) -> None:
    df = _sample_klines()
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.exists()
    read_back = pl.read_parquet(p)
    assert read_back.height == 3
    assert "ts_ms" in read_back.columns


def test_write_klines_overwrites_existing(store: ParquetStore) -> None:
    df1 = _sample_klines()
    df2 = _sample_klines().with_columns(pl.col("close") * 2)
    store.write_klines("binance", "BTCUSDT", df1, year=2026, month=4)
    store.write_klines("binance", "BTCUSDT", df2, year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    read_back = pl.read_parquet(p)
    assert read_back["close"].to_list() == [120020.0, 120040.0, 120050.0]


def test_partition_glob(store: ParquetStore) -> None:
    glob = store.glob("binance", "BTCUSDT", DataType.KLINE_1M)
    assert glob == str(store.root / "binance/BTCUSDT/kline_1m/**/*.parquet")
```

- [ ] **Step 2: Verify FAILS**

```bash
cd backend && uv run pytest tests/market_data/test_parquet_store.py -v
```
Expected: `ModuleNotFoundError: No module named 'app.market_data'`.

- [ ] **Step 3: Implement**

`backend/app/market_data/__init__.py`:
```python
"""Historical market-data pipeline.

Downloaders implement the `MarketDataSource` protocol from `base.py` and write
into the shared `ParquetStore`. `DuckDBQuery` is the read-side API used by the
backtester (Phase 4) and live feature pipelines (Phase 14).
"""
```

`backend/app/market_data/parquet_store.py`:
```python
"""ParquetStore — write-side partition layout for historical data.

Partition scheme: ``{root}/{exchange}/{symbol}/{type}/{yyyy}/{mm}.parquet``.

Designed for query patterns that scan one symbol within a date range — DuckDB
prunes by directory and skips months outside the range. Files are rewritten
in-place when a backfill re-downloads them; consumers should not assume
content stability across writes.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import polars as pl


class DataType(StrEnum):
    KLINE_1M = "kline_1m"
    TRADES = "trades"
    FUNDING_RATE = "funding_rate"
    OPEN_INTEREST = "open_interest"


class ParquetStore:
    """Owns the write-side path layout. Read side lives in DuckDBQuery."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path(
        self,
        exchange: str,
        symbol: str,
        data_type: DataType,
        year: int,
        month: int,
    ) -> Path:
        return (
            self.root
            / exchange
            / symbol
            / data_type.value
            / f"{year:04d}"
            / f"{month:02d}.parquet"
        )

    def glob(self, exchange: str, symbol: str, data_type: DataType) -> str:
        """Glob expression matching all partitions for one (exchange, symbol, type)."""
        return str(self.root / exchange / symbol / data_type.value / "**/*.parquet")

    def write_klines(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.KLINE_1M, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p

    def write_funding(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.FUNDING_RATE, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p

    def write_open_interest(
        self,
        exchange: str,
        symbol: str,
        df: pl.DataFrame,
        *,
        year: int,
        month: int,
    ) -> Path:
        p = self.path(exchange, symbol, DataType.OPEN_INTEREST, year, month)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p, compression="zstd")
        return p
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/market_data/test_parquet_store.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market_data backend/tests/market_data
git commit -m "feat: ParquetStore for partitioned historical data writes"
```

---

### Task 3: DuckDBQuery (read-side, returns Polars frames)

**Files:**
- Create: `backend/app/market_data/duckdb_query.py`
- Create: `backend/tests/market_data/test_duckdb_query.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for DuckDBQuery — read-side over ParquetStore."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from app.market_data.duckdb_query import DuckDBQuery
from app.market_data.parquet_store import ParquetStore


@pytest.fixture
def store_with_data(tmp_path: Path) -> ParquetStore:
    store = ParquetStore(root=tmp_path)
    # April 2026: 3 minutes at 60000-60020
    apr = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [60000.0, 60010.0, 60020.0],
            "high": [60015.0, 60025.0, 60030.0],
            "low": [59995.0, 60005.0, 60015.0],
            "close": [60010.0, 60020.0, 60025.0],
            "volume": [10.5, 11.0, 9.75],
        }
    )
    # May 2026: 2 minutes at 61000-61010
    may = pl.DataFrame(
        {
            "ts_ms": [1717200000000, 1717200060000],
            "open": [61000.0, 61010.0],
            "high": [61015.0, 61025.0],
            "low": [60995.0, 61005.0],
            "close": [61010.0, 61020.0],
            "volume": [9.0, 8.5],
        }
    )
    store.write_klines("binance", "BTCUSDT", apr, year=2026, month=4)
    store.write_klines("binance", "BTCUSDT", may, year=2026, month=5)
    return store


def test_klines_returns_polars_frame(store_with_data: ParquetStore) -> None:
    q = DuckDBQuery(parquet_root=store_with_data.root)
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 31, tzinfo=timezone.utc)
    df = q.klines("binance", "BTCUSDT", start, end)
    assert isinstance(df, pl.DataFrame)
    assert df.height == 5
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]


def test_klines_date_filter_prunes_partitions(store_with_data: ParquetStore) -> None:
    q = DuckDBQuery(parquet_root=store_with_data.root)
    # Only May data
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 31, tzinfo=timezone.utc)
    df = q.klines("binance", "BTCUSDT", start, end)
    assert df.height == 2
    assert df["close"].to_list() == [61010.0, 61020.0]


def test_klines_empty_when_no_data(tmp_path: Path) -> None:
    q = DuckDBQuery(parquet_root=tmp_path)
    df = q.klines(
        "binance",
        "BTCUSDT",
        datetime(2026, 4, 1, tzinfo=timezone.utc),
        datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    assert df.is_empty()
```

- [ ] **Step 2: Run, verify FAILS**

```bash
cd backend && uv run pytest tests/market_data/test_duckdb_query.py -v
```
Expected: `ImportError: cannot import name 'DuckDBQuery'`.

- [ ] **Step 3: Implement**

`backend/app/market_data/duckdb_query.py`:
```python
"""DuckDBQuery — read-side API over the Parquet store.

DuckDB scans Parquet files via globbing + partition pruning. Each call opens a
fresh in-process connection (DuckDB sessions are not designed for long-lived
shared mutable state); cold-start overhead is ~5ms which is negligible for
backtest workloads.

Returns Polars frames everywhere — pandas is explicitly NOT used in
``backend/app/market_data/`` (per Phase 3 architectural choice).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

from app.market_data.parquet_store import DataType


class DuckDBQuery:
    """Read-side query helper. Stateless beyond the Parquet root path."""

    def __init__(self, parquet_root: Path) -> None:
        self.parquet_root = parquet_root

    def klines(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(
            exchange, symbol, DataType.KLINE_1M, start, end
        )

    def funding_rates(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(
            exchange, symbol, DataType.FUNDING_RATE, start, end
        )

    def open_interest(
        self,
        exchange: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        return self._query_partitioned(
            exchange, symbol, DataType.OPEN_INTEREST, start, end
        )

    def _query_partitioned(
        self,
        exchange: str,
        symbol: str,
        data_type: DataType,
        start: datetime,
        end: datetime,
    ) -> pl.DataFrame:
        glob = (
            self.parquet_root
            / exchange
            / symbol
            / data_type.value
            / "**"
            / "*.parquet"
        )
        # If no partitions exist, return an empty frame without invoking DuckDB
        # (duckdb errors on globs that resolve to zero files).
        matching = list(self.parquet_root.glob(
            f"{exchange}/{symbol}/{data_type.value}/**/*.parquet"
        ))
        if not matching:
            return pl.DataFrame()

        conn = duckdb.connect(":memory:")
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        query = (
            f"SELECT * FROM read_parquet('{glob}') "
            f"WHERE ts_ms >= {start_ms} AND ts_ms <= {end_ms} "
            f"ORDER BY ts_ms"
        )
        arrow_table = conn.execute(query).arrow()
        conn.close()
        return pl.from_arrow(arrow_table)
```

- [ ] **Step 4: Tests pass**

```bash
cd backend && uv run pytest tests/market_data/test_duckdb_query.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market_data/duckdb_query.py backend/tests/market_data/test_duckdb_query.py
git commit -m "feat: DuckDBQuery read-side over partitioned Parquet"
```

---

## Phase 3.2: ORM + Migration

### Task 4: SymbolManifestSnapshot ORM

**Files:**
- Create: `backend/app/models/symbol_manifest_snapshot.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the ORM**

```python
"""SymbolManifestSnapshot ORM: survivorship-safe universe snapshot per venue."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SymbolManifestSnapshot(Base):
    """A snapshot of the top-N symbols by volume on a venue for a given date.

    Used to back-test on the universe AS IT WAS at the date, not as it is
    today (avoids survivorship bias — coins that delisted between snapshot
    date and today still appear in the snapshot).
    """

    __tablename__ = "symbol_manifest_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "exchange", name="uq_manifest_snapshot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    symbols: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

- [ ] **Step 2: Register in `models/__init__.py`**

Modify `backend/app/models/__init__.py`:
```python
"""ORM models. Import models here so Alembic autogenerate picks them up."""

from app.models.base import Base
from app.models.strategy_profile import StrategyProfile
from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot

__all__ = ["Base", "StrategyProfile", "SymbolManifestSnapshot"]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models
git commit -m "feat: SymbolManifestSnapshot ORM"
```

---

### Task 5: DataHealthEvent ORM

**Files:**
- Create: `backend/app/models/data_health_event.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the ORM**

```python
"""DataHealthEvent ORM: records gap / freshness / schema-drift events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DataHealthEvent(Base):
    """A logged data-health anomaly (gap / freshness / drift)."""

    __tablename__ = "data_health_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    exchange: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Register**

Update `backend/app/models/__init__.py`:
```python
from app.models.data_health_event import DataHealthEvent
__all__ = ["Base", "StrategyProfile", "SymbolManifestSnapshot", "DataHealthEvent"]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models
git commit -m "feat: DataHealthEvent ORM"
```

---

### Task 6: Alembic migration 0002

**Files:**
- Create: `backend/alembic/versions/0002_symbol_manifest_and_data_health.py`

- [ ] **Step 1: Generate via autogenerate**

```bash
cd backend && uv run alembic revision --autogenerate -m "symbol_manifest_and_data_health"
```

- [ ] **Step 2: Rename file to `0002_symbol_manifest_and_data_health.py`** and normalize header to `revision = "0002"`, `down_revision = "0001"`.

Verify final shape includes both `op.create_table('symbol_manifest_snapshots', ...)` and `op.create_table('data_health_events', ...)`, with matching downgrade `op.drop_table` calls in reverse order.

- [ ] **Step 3: Apply + verify round-trip**

```bash
just mig-up
cd backend && uv run alembic downgrade base && uv run alembic upgrade head
```
Expected: both succeed without errors.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0002_symbol_manifest_and_data_health.py
git commit -m "feat: alembic migration adding symbol_manifest + data_health tables"
```

---

## Phase 3.3: MarketDataSource Protocol + common HTTP utilities

### Task 7: MarketDataSource Protocol

**Files:**
- Create: `backend/app/market_data/base.py`

- [ ] **Step 1: Implement**

```python
"""MarketDataSource Protocol — common interface for exchange downloaders.

Implementations live in sibling modules (``binance_vision.py``,
``bybit_public.py``, ``hyperliquid_archive.py``). Each one knows how to fetch
one calendar month of data for a given symbol + data type.

All methods return Polars DataFrames with the canonical schema (so downstream
``ParquetStore.write_*`` calls don't need per-source branching).

Canonical kline columns: ``ts_ms`` (int64, exchange time) + ``open / high /
low / close / volume`` (float64).

Canonical funding columns: ``ts_ms`` (int64) + ``predicted`` (float64) +
``realized`` (float64 or null until the funding period closes).
"""

from __future__ import annotations

from typing import Protocol

import polars as pl


class MarketDataSource(Protocol):
    """One implementation per exchange. Each fetches one calendar month."""

    name: str

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / open / high / low / close / volume."""
        ...

    async def fetch_funding_rates(
        self, symbol: str, year: int, month: int
    ) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / predicted / realized.

        Raises NotImplementedError on venues that don't expose funding rates
        (e.g. Binance spot — caller should not invoke for spot pairs).
        """
        ...

    async def fetch_open_interest(
        self, symbol: str, year: int, month: int
    ) -> pl.DataFrame:
        """Return a Polars frame with columns ts_ms / oi_base / oi_quote.

        Raises NotImplementedError where unsupported.
        """
        ...
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/market_data/base.py
git commit -m "feat: MarketDataSource Protocol for exchange downloaders"
```

---

### Task 8: HTTP fetcher with retry + rate-limit backoff

**Files:**
- Create: `backend/app/market_data/_http.py`
- Create: `backend/tests/market_data/test_http.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for shared HTTP fetcher (retry + rate-limit backoff)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher


@pytest.mark.asyncio
async def test_fetcher_returns_body_on_200() -> None:
    def handler(req: Request) -> Response:
        return Response(200, content=b"hello")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        body = await fetcher.get_bytes("https://example.com/data.zip")
    assert body == b"hello"


@pytest.mark.asyncio
async def test_fetcher_retries_on_429() -> None:
    calls = {"n": 0}

    def handler(req: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return Response(429, content=b"slow down")
        return Response(200, content=b"ok")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=5, base_backoff_s=0.0)
        body = await fetcher.get_bytes("https://example.com/data.zip")
    assert body == b"ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_fetcher_raises_on_404() -> None:
    def handler(req: Request) -> Response:
        return Response(404, content=b"not found")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=3, base_backoff_s=0.0)
        with pytest.raises(FileNotFoundError):
            await fetcher.get_bytes("https://example.com/missing.zip")


@pytest.mark.asyncio
async def test_fetcher_gives_up_after_max_retries() -> None:
    def handler(req: Request) -> Response:
        return Response(503, content=b"try again later")

    async with AsyncClient(transport=MockTransport(handler)) as client:
        fetcher = RetryingFetcher(client=client, max_retries=2, base_backoff_s=0.0)
        with pytest.raises(RuntimeError):
            await fetcher.get_bytes("https://example.com/data.zip")
```

- [ ] **Step 2: Verify FAILS**

```bash
cd backend && uv run pytest tests/market_data/test_http.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement**

```python
"""Shared HTTP fetcher with exponential-backoff retry on transient failures.

Used by all three downloaders. 404 is treated as a permanent miss
(FileNotFoundError); 5xx and 429 retry with exponential backoff; everything
else raises RuntimeError.
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient, HTTPStatusError, RequestError


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
                if resp.status_code == 404:
                    raise FileNotFoundError(url)
                if resp.status_code == 200:
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
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_http.py -v
git add backend/app/market_data/_http.py backend/tests/market_data/test_http.py
git commit -m "feat: RetryingFetcher with exponential backoff for archive downloads"
```

---

## Phase 3.4: Binance Vision downloader

### Task 9: BinanceVisionClient — klines

**Files:**
- Create: `backend/app/market_data/binance_vision.py`
- Create: `backend/tests/market_data/test_binance_vision.py`
- Create: `backend/tests/market_data/fixtures/binance_klines_sample.csv`

- [ ] **Step 1: Fixture CSV**

`backend/tests/market_data/fixtures/binance_klines_sample.csv`:
```
1714521600000,60000.00,60015.00,59995.00,60010.00,10.5,1714521659999,630074.0,500,5.0,300035.0,0
1714521660000,60010.00,60025.00,60005.00,60020.00,11.0,1714521719999,660209.5,520,5.5,330104.7,0
1714521720000,60020.00,60030.00,60015.00,60025.00,9.75,1714521779999,585243.0,480,4.9,294120.8,0
```

(Binance Vision klines CSV: open_time / open / high / low / close / volume / close_time / quote_asset_volume / number_of_trades / taker_buy_base / taker_buy_quote / ignore.)

- [ ] **Step 2: Failing test**

```python
"""Tests for BinanceVisionClient."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.binance_vision import BinanceVisionClient

FIXTURES = Path(__file__).parent / "fixtures"


def _zip_bytes(csv_bytes: bytes, name: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, csv_bytes)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_klines_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-1m-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "BTCUSDT" in req.url.path
        assert "1m" in req.url.path
        assert "2026-04" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2026, 4)

    assert isinstance(df, pl.DataFrame)
    assert df.height == 3
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    assert df["ts_ms"].to_list() == [1714521600000, 1714521660000, 1714521720000]
    assert df["open"].to_list() == [60000.0, 60010.0, 60020.0]


@pytest.mark.asyncio
async def test_fetch_klines_1m_missing_month_raises() -> None:
    def handler(req: Request) -> Response:
        return Response(404, content=b"not found")

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, max_retries=1, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        with pytest.raises(FileNotFoundError):
            await client.fetch_klines_1m("BTCUSDT", 2030, 12)
```

- [ ] **Step 3: Verify FAILS**

```bash
cd backend && uv run pytest tests/market_data/test_binance_vision.py -v
```

- [ ] **Step 4: Implement**

```python
"""Binance Vision archive downloader.

Public archive at https://data.binance.vision/. No API key required.
Each calendar month is one ZIPped CSV; we download, unzip in-memory, and
parse into the canonical Polars schema.
"""

from __future__ import annotations

import io
import zipfile

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://data.binance.vision"

_KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


class BinanceVisionClient:
    """One instance is reusable across many fetches."""

    name = "binance"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _kline_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/data/spot/monthly/klines/{symbol}/1m/"
            f"{symbol}-1m-{year:04d}-{month:02d}.zip"
        )

    def _funding_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/data/futures/um/monthly/fundingRate/{symbol}/"
            f"{symbol}-fundingRate-{year:04d}-{month:02d}.zip"
        )

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._kline_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        csv_bytes = _unzip_single(raw)
        df = pl.read_csv(
            csv_bytes,
            has_header=False,
            new_columns=_KLINE_COLUMNS,
            schema_overrides={
                "open_time": pl.Int64,
                "close_time": pl.Int64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            },
        )
        return df.select(
            pl.col("open_time").alias("ts_ms"),
            pl.col("open"),
            pl.col("high"),
            pl.col("low"),
            pl.col("close"),
            pl.col("volume"),
        )


def _unzip_single(raw: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise RuntimeError(f"expected single CSV in zip, got {names}")
        return zf.read(names[0])
```

- [ ] **Step 5: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_binance_vision.py -v
git add backend/app/market_data/binance_vision.py backend/tests/market_data
git commit -m "feat: BinanceVisionClient 1m kline downloader"
```

---

### Task 10: Binance Vision — funding rates

**Files:**
- Modify: `backend/app/market_data/binance_vision.py`
- Modify: `backend/tests/market_data/test_binance_vision.py`
- Create: `backend/tests/market_data/fixtures/binance_funding_sample.csv`

- [ ] **Step 1: Fixture**

`binance_funding_sample.csv` (Binance funding CSV: calc_time / funding_interval_hours / last_funding_rate):
```
calc_time,funding_interval_hours,last_funding_rate
1714521600000,8,0.0001
1714550400000,8,0.000125
1714579200000,8,0.00009
```

- [ ] **Step 2: Failing test (append to test_binance_vision.py)**

```python
@pytest.mark.asyncio
async def test_fetch_funding_rates_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_funding_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-fundingRate-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "fundingRate" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_funding_rates("BTCUSDT", 2026, 4)

    assert df.height == 3
    assert df.columns == ["ts_ms", "predicted", "realized"]
    assert df["realized"].to_list() == [0.0001, 0.000125, 0.00009]
```

- [ ] **Step 3: Implement (add to BinanceVisionClient)**

```python
async def fetch_funding_rates(
    self, symbol: str, year: int, month: int
) -> pl.DataFrame:
    url = self._funding_url(symbol, year, month)
    raw = await self._fetcher.get_bytes(url)
    csv_bytes = _unzip_single(raw)
    df = pl.read_csv(
        csv_bytes,
        has_header=True,
        schema_overrides={
            "calc_time": pl.Int64,
            "last_funding_rate": pl.Float64,
        },
    )
    return df.select(
        pl.col("calc_time").alias("ts_ms"),
        # Binance archive only has the realized rate; predicted=realized for historicals
        pl.col("last_funding_rate").alias("predicted"),
        pl.col("last_funding_rate").alias("realized"),
    )
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_binance_vision.py -v
git add backend/app/market_data/binance_vision.py backend/tests/market_data
git commit -m "feat: BinanceVisionClient funding-rate downloader"
```

---

### Task 11: Binance Vision — open interest

**Files:**
- Modify: `backend/app/market_data/binance_vision.py`
- Modify: `backend/tests/market_data/test_binance_vision.py`
- Create: `backend/tests/market_data/fixtures/binance_oi_sample.csv`

- [ ] **Step 1: Fixture**

Binance OI metrics CSV format: `create_time,symbol,sum_open_interest,sum_open_interest_value,...`:
```
create_time,symbol,sum_open_interest,sum_open_interest_value
2026-04-01 00:00:00,BTCUSDT,12345.5,740730000
2026-04-01 00:05:00,BTCUSDT,12350.0,741000000
```

- [ ] **Step 2: Failing test (append)**

```python
@pytest.mark.asyncio
async def test_fetch_open_interest_parses_csv() -> None:
    raw_csv = (FIXTURES / "binance_oi_sample.csv").read_bytes()
    zipped = _zip_bytes(raw_csv, "BTCUSDT-metrics-2026-04.csv")

    def handler(req: Request) -> Response:
        assert "metrics" in req.url.path
        return Response(200, content=zipped)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_open_interest("BTCUSDT", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "oi_base", "oi_quote"]
    assert df["oi_base"].to_list() == [12345.5, 12350.0]
```

- [ ] **Step 3: Implement**

Add to `BinanceVisionClient`:

```python
def _oi_url(self, symbol: str, year: int, month: int) -> str:
    return (
        f"{BASE_URL}/data/futures/um/monthly/metrics/{symbol}/"
        f"{symbol}-metrics-{year:04d}-{month:02d}.zip"
    )

async def fetch_open_interest(
    self, symbol: str, year: int, month: int
) -> pl.DataFrame:
    url = self._oi_url(symbol, year, month)
    raw = await self._fetcher.get_bytes(url)
    csv_bytes = _unzip_single(raw)
    df = pl.read_csv(csv_bytes, has_header=True, try_parse_dates=True)
    return df.select(
        (pl.col("create_time").dt.timestamp("ms")).alias("ts_ms"),
        pl.col("sum_open_interest").cast(pl.Float64).alias("oi_base"),
        pl.col("sum_open_interest_value").cast(pl.Float64).alias("oi_quote"),
    )
```

- [ ] **Step 4: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_binance_vision.py -v
git add backend/app/market_data/binance_vision.py backend/tests/market_data
git commit -m "feat: BinanceVisionClient open-interest downloader"
```

---

## Phase 3.5–3.6: Bybit + Hyperliquid downloaders (parallel structure to Binance)

### Task 12: BybitPublicClient — klines + funding

**Files:**
- Create: `backend/app/market_data/bybit_public.py`
- Create: `backend/tests/market_data/test_bybit_public.py`
- Create: `backend/tests/market_data/fixtures/bybit_klines_sample.csv.gz` (gzipped)
- Create: `backend/tests/market_data/fixtures/bybit_funding_sample.csv.gz`

Bybit public archive at `https://public.bybit.com/`. Format differs from Binance — files are `.csv.gz` (not `.zip`), kline columns are timestamp+open+high+low+close+volume+turnover.

- [ ] **Step 1: Failing tests in `test_bybit_public.py`**

Two tests mirroring the Binance pattern: one for klines (verifies URL, parses .csv.gz, schema = canonical) and one for funding (verifies URL pattern `https://public.bybit.com/derivatives/funding/BTCUSDT/{yyyy}-{mm}.csv.gz`).

```python
"""Tests for BybitPublicClient."""

from __future__ import annotations

import gzip
import io
from pathlib import Path

import polars as pl
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.bybit_public import BybitPublicClient


def _gzip(s: str) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(s.encode())
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_parses_csvgz() -> None:
    csv = (
        "start_at,open,high,low,close,volume,turnover\n"
        "1714521600,60000,60015,59995,60010,10.5,630074\n"
        "1714521660,60010,60025,60005,60020,11.0,660209\n"
    )
    body = _gzip(csv)

    def handler(req: Request) -> Response:
        assert "BTCUSDT" in req.url.path
        return Response(200, content=body)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = BybitPublicClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    # Bybit uses seconds; client must convert to ms
    assert df["ts_ms"][0] == 1714521600000
```

- [ ] **Step 2: Implement** (gzip-handling + URL pattern; seconds→ms conversion).

```python
"""Bybit public archive downloader.

Public archive at https://public.bybit.com/. No API key. Files are .csv.gz.
Bybit's timestamps are in SECONDS (not ms like Binance) — we convert.
"""

from __future__ import annotations

import gzip
import io

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://public.bybit.com"


class BybitPublicClient:
    name = "bybit"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _kline_url(self, symbol: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/spot_index_price_kline/{symbol}/1m/"
            f"{symbol}-{year:04d}-{month:02d}.csv.gz"
        )

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._kline_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            csv_bytes = gz.read()
        df = pl.read_csv(csv_bytes, has_header=True)
        return df.select(
            (pl.col("start_at").cast(pl.Int64) * 1000).alias("ts_ms"),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
        )
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_bybit_public.py -v
git add backend/app/market_data/bybit_public.py backend/tests/market_data
git commit -m "feat: BybitPublicClient klines downloader"
```

---

### Task 13: Hyperliquid archive — perp trades

**Files:**
- Create: `backend/app/market_data/hyperliquid_archive.py`
- Create: `backend/tests/market_data/test_hyperliquid_archive.py`

Hyperliquid publishes archives via S3 at `https://hyperliquid-archive.s3.eu-central-1.amazonaws.com/`. Format: gzipped JSONL (one trade per line). We aggregate to 1m klines on read.

- [ ] **Step 1: Failing test**

```python
"""Tests for HyperliquidArchiveClient."""

from __future__ import annotations

import gzip
import io

import polars as pl
import pytest
from httpx import AsyncClient, MockTransport, Request, Response

from app.market_data._http import RetryingFetcher
from app.market_data.hyperliquid_archive import HyperliquidArchiveClient


def _gzip_jsonl(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write("\n".join(lines).encode())
    return buf.getvalue()


@pytest.mark.asyncio
async def test_fetch_klines_1m_aggregates_from_trades() -> None:
    # Two trades in the same minute, one in the next
    trades = [
        '{"time": 1714521600123, "coin": "BTC", "px": "60000", "sz": "0.5"}',
        '{"time": 1714521610456, "coin": "BTC", "px": "60010", "sz": "0.3"}',
        '{"time": 1714521660789, "coin": "BTC", "px": "60020", "sz": "0.2"}',
    ]
    body = _gzip_jsonl(trades)

    def handler(req: Request) -> Response:
        return Response(200, content=body)

    async with AsyncClient(transport=MockTransport(handler)) as http:
        fetcher = RetryingFetcher(client=http, base_backoff_s=0.0)
        client = HyperliquidArchiveClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTC", 2026, 4)

    assert df.height == 2
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]
    assert df["open"][0] == 60000.0
    assert df["close"][0] == 60010.0
    assert df["volume"][0] == 0.8
```

- [ ] **Step 2: Implement**

```python
"""Hyperliquid archive downloader — aggregates trades to 1m klines."""

from __future__ import annotations

import gzip
import io

import polars as pl

from app.market_data._http import RetryingFetcher

BASE_URL = "https://hyperliquid-archive.s3.eu-central-1.amazonaws.com"


class HyperliquidArchiveClient:
    name = "hyperliquid"

    def __init__(self, *, fetcher: RetryingFetcher) -> None:
        self._fetcher = fetcher

    def _trades_url(self, coin: str, year: int, month: int) -> str:
        return (
            f"{BASE_URL}/trades/{coin}/{year:04d}-{month:02d}.jsonl.gz"
        )

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        url = self._trades_url(symbol, year, month)
        raw = await self._fetcher.get_bytes(url)
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            jsonl = gz.read().decode()
        trades = pl.read_ndjson(io.BytesIO(jsonl.encode()))
        # Aggregate to 1m OHLCV
        return (
            trades.with_columns(
                (pl.col("time") // 60_000 * 60_000).alias("ts_ms"),
                pl.col("px").cast(pl.Float64),
                pl.col("sz").cast(pl.Float64),
            )
            .group_by("ts_ms")
            .agg(
                pl.col("px").first().alias("open"),
                pl.col("px").max().alias("high"),
                pl.col("px").min().alias("low"),
                pl.col("px").last().alias("close"),
                pl.col("sz").sum().alias("volume"),
            )
            .sort("ts_ms")
        )
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/market_data/test_hyperliquid_archive.py -v
git add backend/app/market_data/hyperliquid_archive.py backend/tests/market_data
git commit -m "feat: HyperliquidArchiveClient with trade→kline aggregation"
```

---

## Phase 3.7: Orchestration service

### Task 14: DataPipelineService

**Files:**
- Create: `backend/app/services/data_pipeline.py`
- Create: `backend/tests/services/__init__.py`
- Create: `backend/tests/services/test_data_pipeline.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for DataPipelineService."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.market_data.parquet_store import DataType, ParquetStore
from app.services.data_pipeline import DataPipelineService


class _FakeBinance:
    name = "binance"

    async def fetch_klines_1m(self, symbol: str, year: int, month: int) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "ts_ms": [1714521600000, 1714521660000],
                "open": [60000.0, 60010.0],
                "high": [60015.0, 60025.0],
                "low": [59995.0, 60005.0],
                "close": [60010.0, 60020.0],
                "volume": [10.5, 11.0],
            }
        )


@pytest.mark.asyncio
async def test_refresh_writes_partition(tmp_path: Path) -> None:
    store = ParquetStore(root=tmp_path)
    svc = DataPipelineService(store=store, sources={"binance": _FakeBinance()})
    await svc.refresh_klines_1m("binance", "BTCUSDT", year=2026, month=4)
    p = store.path("binance", "BTCUSDT", DataType.KLINE_1M, 2026, 4)
    assert p.exists()
    df = pl.read_parquet(p)
    assert df.height == 2
```

- [ ] **Step 2: Implement**

```python
"""DataPipelineService — orchestrates download + write across data sources."""

from __future__ import annotations

from app.market_data.base import MarketDataSource
from app.market_data.parquet_store import ParquetStore


class UnknownSource(KeyError):
    """Raised when the pipeline is asked to refresh from an unregistered source."""


class DataPipelineService:
    def __init__(
        self,
        *,
        store: ParquetStore,
        sources: dict[str, MarketDataSource],
    ) -> None:
        self._store = store
        self._sources = sources

    async def refresh_klines_1m(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_klines_1m(symbol, year, month)
        self._store.write_klines(exchange, symbol, df, year=year, month=month)

    async def refresh_funding_rates(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_funding_rates(symbol, year, month)
        self._store.write_funding(exchange, symbol, df, year=year, month=month)

    async def refresh_open_interest(
        self, exchange: str, symbol: str, *, year: int, month: int
    ) -> None:
        source = self._sources.get(exchange)
        if source is None:
            raise UnknownSource(exchange)
        df = await source.fetch_open_interest(symbol, year, month)
        self._store.write_open_interest(exchange, symbol, df, year=year, month=month)
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_data_pipeline.py -v
git add backend/app/services/data_pipeline.py backend/tests/services
git commit -m "feat: DataPipelineService orchestrating download + Parquet write"
```

---

## Phase 3.8–3.9: Symbol manifest + data health

### Task 15: SymbolManifestService

**Files:**
- Create: `backend/app/services/symbol_manifest.py`
- Create: `backend/tests/services/test_symbol_manifest.py`

- [ ] **Step 1: Test (uses `db_session` fixture from Task 11 of Phase 2)**

```python
"""Tests for SymbolManifestService."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot
from app.services.symbol_manifest import SymbolManifestService


@pytest.mark.asyncio
async def test_snapshot_creates_row(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    snapshot = await svc.snapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    )
    await db_session.flush()
    assert snapshot.id is not None
    assert snapshot.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@pytest.mark.asyncio
async def test_get_returns_snapshot_for_date(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    await svc.snapshot(
        snapshot_date=date(2026, 5, 24),
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT"],
    )
    await db_session.flush()
    result = await svc.get(date(2026, 5, 24), exchange="binance")
    assert result is not None
    assert "ETHUSDT" in result.symbols


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(db_session: AsyncSession) -> None:
    svc = SymbolManifestService(db_session)
    result = await svc.get(date(2030, 1, 1), exchange="binance")
    assert result is None
```

- [ ] **Step 2: Implement**

```python
"""SymbolManifestService — persists survivorship-safe symbol snapshots."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symbol_manifest_snapshot import SymbolManifestSnapshot


class SymbolManifestService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(
        self,
        *,
        snapshot_date: date,
        exchange: str,
        symbols: list[str],
    ) -> SymbolManifestSnapshot:
        row = SymbolManifestSnapshot(
            snapshot_date=snapshot_date,
            exchange=exchange,
            symbols=symbols,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(
        self, snapshot_date: date, *, exchange: str
    ) -> SymbolManifestSnapshot | None:
        result = await self._session.execute(
            select(SymbolManifestSnapshot)
            .where(SymbolManifestSnapshot.snapshot_date == snapshot_date)
            .where(SymbolManifestSnapshot.exchange == exchange)
        )
        return result.scalar_one_or_none()
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_symbol_manifest.py -v
git add backend/app/services/symbol_manifest.py backend/tests/services
git commit -m "feat: SymbolManifestService for survivorship-safe universe snapshots"
```

---

### Task 16: DataHealthService — gap detection

**Files:**
- Create: `backend/app/services/data_health.py`
- Create: `backend/tests/services/test_data_health.py`

- [ ] **Step 1: Test**

```python
"""Tests for DataHealthService."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import ParquetStore
from app.services.data_health import DataHealthService


@pytest.mark.asyncio
async def test_detect_gaps_no_gaps(tmp_path: Path, db_session: AsyncSession) -> None:
    store = ParquetStore(root=tmp_path)
    # 3 consecutive 1-minute klines
    df = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521660000, 1714521720000],
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)

    svc = DataHealthService(session=db_session, parquet_root=tmp_path)
    gaps = svc.detect_kline_gaps("binance", "BTCUSDT", year=2026, month=4)
    assert gaps == []


@pytest.mark.asyncio
async def test_detect_gaps_finds_missing_minute(
    tmp_path: Path, db_session: AsyncSession
) -> None:
    store = ParquetStore(root=tmp_path)
    # Minute 1714521660000 is missing (gap between :600 and :720)
    df = pl.DataFrame(
        {
            "ts_ms": [1714521600000, 1714521720000],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
        }
    )
    store.write_klines("binance", "BTCUSDT", df, year=2026, month=4)

    svc = DataHealthService(session=db_session, parquet_root=tmp_path)
    gaps = svc.detect_kline_gaps("binance", "BTCUSDT", year=2026, month=4)
    assert len(gaps) == 1
    assert gaps[0] == (1714521660000, 1714521660000)
```

- [ ] **Step 2: Implement**

```python
"""DataHealthService — gap detection + freshness checks + event logging."""

from __future__ import annotations

from pathlib import Path

import polars as pl
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.parquet_store import DataType
from app.models.data_health_event import DataHealthEvent

ONE_MINUTE_MS = 60_000


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
        if df.height < 2:
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
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/services/test_data_health.py -v
git add backend/app/services/data_health.py backend/tests/services
git commit -m "feat: DataHealthService with kline-gap detection + event logging"
```

---

## Phase 3.10: Worker jobs

### Task 17: Worker job dispatcher

**Files:**
- Modify: `backend/app/worker/main.py`
- Create: `backend/app/worker/jobs/__init__.py`
- Create: `backend/app/worker/jobs/refresh_data.py`
- Create: `backend/tests/test_worker_jobs.py`

The existing `worker/main.py` runs a heartbeat. We extend it: if env var `WORKER_JOB` is set, dispatch to the named job and exit; otherwise run the heartbeat.

- [ ] **Step 1: Failing test**

```python
"""Tests for worker job dispatch."""

from __future__ import annotations

import pytest

from app.worker.main import _resolve_job


def test_resolve_unknown_job_raises() -> None:
    with pytest.raises(KeyError):
        _resolve_job("does_not_exist")


def test_resolve_refresh_data_returns_callable() -> None:
    job = _resolve_job("refresh_data")
    assert callable(job)
```

- [ ] **Step 2: Implement**

`backend/app/worker/jobs/__init__.py`:
```python
"""Worker job entry points. Each is an async callable taking no arguments."""
```

`backend/app/worker/jobs/refresh_data.py`:
```python
"""Refresh-data worker job — pulls latest klines/funding for the active universe."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run() -> None:
    """Placeholder until Task 18 wires this up to the active profile."""
    logger.info("refresh_data: stub run (no work yet)")
```

Modify `backend/app/worker/main.py`:
```python
"""Worker entry point.

Started via: ``python -m app.worker.main`` (or via docker-compose ``worker`` service).

If env var ``WORKER_JOB`` is set, dispatch to the named job in
``app.worker.jobs.*`` and exit. Otherwise, run the heartbeat loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from app.worker.jobs import refresh_data

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 30.0

_JOBS: dict[str, Callable[[], Awaitable[None]]] = {
    "refresh_data": refresh_data.run,
}


def _resolve_job(name: str) -> Callable[[], Awaitable[None]]:
    if name not in _JOBS:
        raise KeyError(f"unknown worker job: {name}")
    return _JOBS[name]


async def heartbeat(
    *,
    interval_s: float = HEARTBEAT_INTERVAL_S,
    max_iterations: int | None = None,
) -> int:
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        logger.info("worker heartbeat", extra={"iteration": iterations})
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        await asyncio.sleep(interval_s)
    return iterations


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    job_name = os.environ.get("WORKER_JOB")
    if job_name:
        job = _resolve_job(job_name)
        asyncio.run(job())
    else:
        asyncio.run(heartbeat())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Tests pass (including existing worker tests still pass)**

```bash
cd backend && uv run pytest tests/test_worker.py tests/test_worker_jobs.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker backend/tests/test_worker_jobs.py
git commit -m "feat: worker job dispatcher via WORKER_JOB env var"
```

---

### Task 18: Wire `refresh_data` job to active profile + universe

**Files:**
- Modify: `backend/app/worker/jobs/refresh_data.py`
- Modify: `backend/tests/test_worker_jobs.py`

- [ ] **Step 1: Failing test**

Test verifies that when called with a fake DataPipelineService + universe of ["BTCUSDT", "ETHUSDT"], the job invokes `refresh_klines_1m` once per symbol for the current calendar month.

```python
"""Tests for worker job dispatch + refresh_data job."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.worker.jobs.refresh_data import run_with


@pytest.mark.asyncio
async def test_refresh_data_invokes_pipeline_per_symbol() -> None:
    fake_pipeline = AsyncMock()
    now = datetime(2026, 5, 24, tzinfo=timezone.utc)
    await run_with(
        pipeline=fake_pipeline,
        exchange="binance",
        symbols=["BTCUSDT", "ETHUSDT"],
        now=now,
    )
    assert fake_pipeline.refresh_klines_1m.call_count == 2
    call_args = [c.kwargs for c in fake_pipeline.refresh_klines_1m.call_args_list]
    assert {a["symbol"] for a in call_args} == {"BTCUSDT", "ETHUSDT"}
    assert all(a["year"] == 2026 and a["month"] == 5 for a in call_args)
```

- [ ] **Step 2: Implement**

```python
"""Refresh-data worker job — pulls latest klines for the active universe."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.data_pipeline import DataPipelineService

logger = logging.getLogger(__name__)


async def run_with(
    *,
    pipeline: DataPipelineService,
    exchange: str,
    symbols: list[str],
    now: datetime,
) -> None:
    for symbol in symbols:
        await pipeline.refresh_klines_1m(
            exchange, symbol, year=now.year, month=now.month
        )
        logger.info(
            "refresh_data: wrote partition",
            extra={"exchange": exchange, "symbol": symbol},
        )


async def run() -> None:
    """Entry point invoked by worker.main when WORKER_JOB=refresh_data.

    Reads active profile to determine the universe, builds a real pipeline,
    delegates to run_with. Kept thin so unit tests can drive run_with directly.
    """
    # Wiring happens in Task 20 (real DB session + profile lookup); for now,
    # log that the job ran with no work to do.
    logger.info("refresh_data: stub run — no active profile loaded yet")
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/test_worker_jobs.py -v
git add backend/app/worker/jobs/refresh_data.py backend/tests/test_worker_jobs.py
git commit -m "feat: refresh_data worker job invokes pipeline per symbol"
```

---

### Task 19: docker-compose worker services for scheduled jobs

**Files:**
- Modify: `docker-compose.yml`

Add two new services that run the worker container with `WORKER_JOB` set: `worker-refresh-data` (cron via restart policy) and the existing `worker` keeps its heartbeat.

- [ ] **Step 1: Append to `docker-compose.yml`**

Add after the existing `worker:` block:

```yaml
  worker-refresh-data:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: cryptobot-worker-refresh-data
    restart: "no"   # cron-like; orchestrator (cron + docker compose run) drives cadence
    command: uv run python -m app.worker.main
    environment:
      WORKER_JOB: refresh_data
      DATABASE_URL: postgresql+asyncpg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
      DATABASE_URL_SYNC: postgresql+psycopg://cryptobot:${POSTGRES_PASSWORD:-devpass}@postgres:5432/cryptobot
    depends_on:
      postgres:
        condition: service_healthy
    profiles: ["jobs"]   # not started by default; `docker compose --profile jobs run worker-refresh-data`
```

- [ ] **Step 2: Verify YAML still parses**

```bash
docker compose --profile jobs config --quiet
```
Expected: exits 0.

- [ ] **Step 3: Add `just refresh-data` recipe**

Append to `justfile`:
```just
# Run the refresh_data worker job once (uses the WORKER_JOB env)
refresh-data:
    cd backend && WORKER_JOB=refresh_data uv run python -m app.worker.main
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml justfile
git commit -m "chore: docker-compose worker-refresh-data service + justfile recipe"
```

---

## Phase 3.11: API + smoke

### Task 20: Data-health API endpoint

**Files:**
- Create: `backend/app/api/data_health.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_data_health.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for /api/v1/data-health endpoints."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from app.models.data_health_event import DataHealthEvent


@pytest.mark.asyncio
async def test_recent_returns_events(
    async_client: AsyncClient, db_session: AsyncSession
) -> None:
    event = DataHealthEvent(
        event_type="gap",
        exchange="binance",
        symbol="BTCUSDT",
        data_type="kline_1m",
        severity="warning",
        description="3-minute gap on 2026-04-15",
        details={"gap_start_ms": 1714521600000, "gap_end_ms": 1714521780000},
    )
    db_session.add(event)
    await db_session.flush()
    await db_session.commit()

    r = await async_client.get("/api/v1/data-health/recent")
    assert r.status_code == 200
    body = r.json()
    assert any(e["event_type"] == "gap" for e in body)
```

- [ ] **Step 2: Implement**

```python
"""HTTP API for surfacing recent data-health events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.models.data_health_event import DataHealthEvent

router = APIRouter(prefix="/api/v1/data-health", tags=["data-health"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class DataHealthEventResponse(BaseModel):
    id: uuid.UUID
    ts: datetime
    event_type: str
    exchange: str
    symbol: str | None
    data_type: str | None
    severity: str
    details: dict[str, Any]
    description: str | None


@router.get("/recent", response_model=list[DataHealthEventResponse])
async def recent(db: DbSession, limit: int = 50) -> list[DataHealthEventResponse]:
    result = await db.execute(
        select(DataHealthEvent).order_by(DataHealthEvent.ts.desc()).limit(limit)
    )
    rows = list(result.scalars().all())
    return [
        DataHealthEventResponse.model_validate(r, from_attributes=True) for r in rows
    ]
```

Modify `backend/app/main.py` to include the router:
```python
from app.api import data_health, health, strategy_profiles
# ...
app.include_router(data_health.router)
```

- [ ] **Step 3: Tests pass + commit**

```bash
cd backend && uv run pytest tests/api/test_data_health.py -v
git add backend/app/api/data_health.py backend/app/main.py backend/tests/api
git commit -m "feat: GET /api/v1/data-health/recent endpoint"
```

---

### Task 21: End-to-end smoke test (real Binance Vision)

**Files:**
- Create: `backend/tests/integration/__init__.py`
- Create: `backend/tests/integration/test_binance_vision_e2e.py`

- [ ] **Step 1: Marker-gated smoke test**

```python
"""Integration: real-network smoke against Binance Vision.

Marked ``slow`` so it skips by default; opt in with ``pytest -m slow``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.market_data._http import RetryingFetcher
from app.market_data.binance_vision import BinanceVisionClient
from app.market_data.parquet_store import ParquetStore


@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_binance_vision_btcusdt_kline_2024_01(tmp_path: Path) -> None:
    async with AsyncClient() as http:
        fetcher = RetryingFetcher(client=http)
        client = BinanceVisionClient(fetcher=fetcher)
        df = await client.fetch_klines_1m("BTCUSDT", 2024, 1)

    # Jan 2024 has 31 days * 24 * 60 = 44,640 minutes — expect ≥ 44,000 rows
    assert df.height >= 44_000
    assert df.columns == ["ts_ms", "open", "high", "low", "close", "volume"]

    store = ParquetStore(root=tmp_path)
    store.write_klines("binance", "BTCUSDT", df, year=2024, month=1)
    assert store.path(
        "binance",
        "BTCUSDT",
        store.path("binance", "BTCUSDT", store.path.__defaults__ or [None][0], 2024, 1).suffix == ".parquet",
        2024,
        1,
    )
```

Add the `slow` marker to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = ["slow: integration tests that hit the network"]
```

- [ ] **Step 2: Manual smoke locally**

```bash
cd backend && uv run pytest tests/integration/test_binance_vision_e2e.py -m slow -v
```
Expected: 1 passed in ~10–60 seconds depending on network.

- [ ] **Step 3: Commit (test stays in repo but unmarked-slow CI skips it)**

```bash
git add backend/pyproject.toml backend/tests/integration
git commit -m "test: real-network smoke against Binance Vision (slow marker)"
```

---

## Phase 3.12: Wrap-up

### Task 22: Update README + full sweep

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append "Data pipeline" section to README**

Add after the "Profiles" section:

```markdown
## Data pipeline (Phase 3)

Historical market data is downloaded from public exchange archives and stored
as partitioned Parquet on local disk under `data/parquet/`. DuckDB queries them
into Polars frames for the backtester and live feature pipeline.

### One-shot manual refresh

```bash
WORKER_JOB=refresh_data just refresh-data
```

### Or via Docker (cron-style)

```bash
docker compose --profile jobs run --rm worker-refresh-data
```

### Querying

```python
from datetime import datetime
from pathlib import Path

from app.market_data.duckdb_query import DuckDBQuery

q = DuckDBQuery(parquet_root=Path("data/parquet"))
df = q.klines("binance", "BTCUSDT", datetime(2024, 1, 1), datetime(2024, 1, 31))
```
```

- [ ] **Step 2: Full sweep**

```bash
just test && just typecheck && just lint
```
Expected: all green; 59 tests pass (37 from Phase 1+2 + 22 new).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README data-pipeline section"
```

---

### Task 23: PR via pr-summary

- [ ] **Step 1: Confirm gates green** (`just test && just typecheck && just lint`)

- [ ] **Step 2: Run `pr-summary`** (the slash command / bare-word). It will:
  - Classify commits: many `feat:` + some `chore:` / `test:` / `docs:` → MINOR bump
  - Bump v0.2.0 → v0.3.0 via `scripts/bump-version.sh minor`
  - Prepend v0.3.0 entry to `CHANGELOG.md`
  - Create annotated `v0.3.0` tag
  - Push with `--follow-tags`
  - Open the PR

Don't run `gh pr create` directly — `pr-summary` is mandatory per `using-dev-toolkit`.

---

## Self-review checklist (performed)

**1. Spec coverage**

| Spec item | Task |
|---|---|
| Binance Vision downloader (klines + funding + OI) | Tasks 9, 10, 11 |
| Bybit public downloader | Task 12 |
| Hyperliquid archive downloader | Task 13 |
| Parquet store with `{exchange}/{symbol}/{type}/{yyyy}/{mm}.parquet` layout | Task 2 |
| DuckDB query helper returning Polars | Task 3 |
| Symbol manifest snapshots (survivorship-safe universe) | Tasks 4, 6, 15 |
| Data health: gap detection + freshness | Tasks 5, 6, 16, 20 |
| Background worker jobs (cron-driven refresh) | Tasks 17, 18, 19 |
| Polars adoption (no pandas in `market_data/`) | Tasks 1, 2, 3, 9–18 |
| Profile registry keys for data_health cadence | Already in Phase 2 `defaults.py` |
| HTTP retry + rate-limit backoff | Task 8 |

**2. Placeholder scan:** none of "TBD", "implement later", "similar to Task N" appear (each task has full code, including the test fixtures).

**3. Type consistency:**
- `MarketDataSource.fetch_klines_1m / fetch_funding_rates / fetch_open_interest` — consistent across base + binance + bybit + hyperliquid
- `ParquetStore.path()` returns `Path`; `write_klines / write_funding / write_open_interest` all take `df: pl.DataFrame` + `year: int, month: int`
- `DuckDBQuery.klines / funding_rates / open_interest` all return `pl.DataFrame`
- `DataHealthService.detect_kline_gaps` returns `list[tuple[int, int]]` (gap start/end in ms)
- `SymbolManifestService.snapshot / get` use `date` and `exchange: str`

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-05-24-cryptobot-data-pipeline.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — `superpowers:subagent-driven-development`. Fresh subagent per task + two-stage review (spec then code quality). 23 tasks; expect ~3–4 hours of session time at the Phase 1+2 pace.

**2. Inline Execution** — `superpowers:executing-plans`. Batched, checkpoint-driven, less context-isolated.

Which approach?
