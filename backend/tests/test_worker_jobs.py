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
