"""ProfileParams: the single accessor for every profile-scoped value.

Constraint #1 cashes out here: strategy code calls `params.get(path)` and
nothing else. If a path isn't in the registry, boot fails — no silent
fallbacks to literals.
"""
from __future__ import annotations

from typing import Any

from app.profile.defaults import (
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)

_MISSING = object()


class UnknownParamPath(KeyError):
    """Raised when a path is requested that isn't in any registry."""


class ProfileParams:
    """Resolves dotted-path lookups against a profile JSONB blob.

    Lookup order:
      1. Profile JSONB (nested via dotted path).
      2. Registry default (numeric / string / dict).
      3. UnknownParamPath if path not in any registry.
    """

    def __init__(self, profile: dict[str, Any]) -> None:
        self._profile = profile

    def get(self, path: str) -> Any:
        value = _walk(self._profile, path)
        if value is not _MISSING:
            return value
        if path in PROFILE_SCOPED_DEFAULTS:
            return PROFILE_SCOPED_DEFAULTS[path]
        if path in PROFILE_SCOPED_STRING_DEFAULTS:
            return PROFILE_SCOPED_STRING_DEFAULTS[path]
        if path in PROFILE_SCOPED_DICT_DEFAULTS:
            return PROFILE_SCOPED_DICT_DEFAULTS[path]
        raise UnknownParamPath(
            f"path {path!r} is not in PROFILE_SCOPED_DEFAULTS, _STRING_, or _DICT_"
        )

    def keys(self) -> set[str]:
        """Return every registered path (registry contents)."""
        return all_profile_keys()


def _walk(d: dict[str, Any], path: str) -> Any:
    """Nested dict lookup via dotted path. Returns _MISSING if absent."""
    cur: Any = d
    for segment in path.split("."):
        if not isinstance(cur, dict) or segment not in cur:
            return _MISSING
        cur = cur[segment]
    return cur
