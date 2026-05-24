"""In-process metrics collector — counters for /api/v1/metrics."""

from __future__ import annotations

from collections import defaultdict, deque

_LATENCY_RING_SIZE = 1000


class MetricsCollector:
    def __init__(self) -> None:
        self.dispatch_count: int = 0
        self.dispatch_failures: int = 0
        self.fills_total: int = 0
        self.fills_partial: int = 0
        self.halts: dict[str, int] = defaultdict(int)
        self.venue_errors: dict[str, int] = defaultdict(int)
        self.dispatch_latencies_ms: deque[float] = deque(maxlen=_LATENCY_RING_SIZE)

    def record_dispatch(self, *, latency_ms: float, status: str) -> None:
        self.dispatch_count += 1
        self.dispatch_latencies_ms.append(latency_ms)
        if status not in ("ok", "auto_rebalance"):
            self.dispatch_failures += 1

    def record_fill(self, *, partial: bool) -> None:
        self.fills_total += 1
        if partial:
            self.fills_partial += 1

    def record_halt(self, halt_class: str) -> None:
        self.halts[halt_class] += 1

    def record_venue_error(self, venue: str) -> None:
        self.venue_errors[venue] += 1

    def reset(self) -> None:
        """Test helper."""
        self.dispatch_count = 0
        self.dispatch_failures = 0
        self.fills_total = 0
        self.fills_partial = 0
        self.halts.clear()
        self.venue_errors.clear()
        self.dispatch_latencies_ms.clear()


# Singleton — imported throughout the app
collector = MetricsCollector()
