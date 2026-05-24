"""Tests for correlation ID context."""

from __future__ import annotations

from app.services.correlation import clear, current, new_id, set_dispatch_id


def test_default_is_none() -> None:
    clear()
    assert current() is None


def test_set_and_get() -> None:
    set_dispatch_id("abc123")
    assert current() == "abc123"
    clear()


def test_new_id_is_unique() -> None:
    a = new_id()
    b = new_id()
    assert a != b
    assert len(a) == 32
