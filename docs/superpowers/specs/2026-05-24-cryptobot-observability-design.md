# Cryptobot Hardening Pass 5 — Observability

**Date**: 2026-05-24

## Goal

1. **Richer Prometheus metrics** — add dispatch-latency histogram, per-venue error counters, fill-success rate, halt counters
2. **Correlation IDs** — every log line + audit row carries a `dispatch_id` to trace a single decision across the OMS + adapter + audit log

## Architecture

### Metrics — in-process counters

`backend/app/services/metrics_collector.py`:

```python
class MetricsCollector:
    """In-process counter store; rendered by /api/v1/metrics."""

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.dispatch_failures = 0
        self.fills_total = 0
        self.fills_partial = 0
        self.halts: dict[str, int] = defaultdict(int)
        self.venue_errors: dict[str, int] = defaultdict(int)
        self.dispatch_latencies_ms: list[float] = []  # bounded ring buffer

    def record_dispatch(self, *, latency_ms: float, status: str) -> None: ...
    def record_fill(self, *, partial: bool) -> None: ...
    def record_halt(self, halt_class: str) -> None: ...
    def record_venue_error(self, venue: str) -> None: ...
```

Singleton `metrics_collector` exposed via `app.services.metrics_collector.collector`. `OMS.dispatch` records on success/failure/halt; adapters' error paths bump venue counters.

`backend/app/api/metrics.py` extended to render the new metrics.

### Correlation IDs

`backend/app/services/correlation.py`:

```python
import contextvars
import uuid

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dispatch_id", default=None
)

def new_id() -> str:
    return uuid.uuid4().hex

def set_dispatch_id(value: str) -> None: ...
def current() -> str | None: ...
```

`JsonFormatter` (logging_config.py) reads from `correlation.current()` and adds `dispatch_id` to every log record.

`OMS.dispatch` starts a new ID at function entry, passes through context, stores on the audit row's `details.dispatch_id`.

## Components

- `backend/app/services/metrics_collector.py` — counter store
- `backend/app/services/correlation.py` — contextvar id
- `backend/app/logging_config.py` — JSON formatter reads correlation
- `backend/app/api/metrics.py` — render new counters
- `backend/app/oms/service.py` — record metrics + set dispatch_id
- `backend/tests/services/test_metrics_collector.py` — 3 tests
- `backend/tests/services/test_correlation.py` — 2 tests
- `backend/tests/api/test_metrics.py` — append 1 test for new metrics

## DoD

~322 tests pass. `/api/v1/metrics` shows dispatch_count, fills_total, halts. Log lines carry `dispatch_id` when set.
