"""Correlation IDs via contextvars — propagated through async dispatch context."""

from __future__ import annotations

import contextvars
import uuid

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dispatch_id", default=None
)


def new_id() -> str:
    return uuid.uuid4().hex


def set_dispatch_id(value: str) -> None:
    _current.set(value)


def current() -> str | None:
    return _current.get()


def clear() -> None:
    _current.set(None)
