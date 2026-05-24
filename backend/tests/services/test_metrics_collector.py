"""Tests for MetricsCollector."""

from __future__ import annotations

from app.services.metrics_collector import MetricsCollector


def test_record_dispatch_increments_count() -> None:
    m = MetricsCollector()
    m.record_dispatch(latency_ms=50.0, status="ok")
    assert m.dispatch_count == 1
    assert m.dispatch_failures == 0


def test_record_dispatch_failure_increments_failures() -> None:
    m = MetricsCollector()
    m.record_dispatch(latency_ms=50.0, status="halted_hedge_drift")
    assert m.dispatch_count == 1
    assert m.dispatch_failures == 1


def test_record_fill_partial_separate() -> None:
    m = MetricsCollector()
    m.record_fill(partial=False)
    m.record_fill(partial=True)
    assert m.fills_total == 2
    assert m.fills_partial == 1


def test_halts_dict_accumulates() -> None:
    m = MetricsCollector()
    m.record_halt("KillSwitchActive")
    m.record_halt("KillSwitchActive")
    m.record_halt("DrawdownBrakeHalt")
    assert m.halts["KillSwitchActive"] == 2
    assert m.halts["DrawdownBrakeHalt"] == 1


def test_latency_ring_buffer_bounded() -> None:
    m = MetricsCollector()
    for i in range(2000):
        m.record_dispatch(latency_ms=float(i), status="ok")
    assert len(m.dispatch_latencies_ms) == 1000
