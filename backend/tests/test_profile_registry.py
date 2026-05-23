"""Tests for profile registry self-consistency."""
from __future__ import annotations

from app.profile.defaults import (
    PROFILE_SCOPED_DEFAULTS,
    PROFILE_SCOPED_DICT_DEFAULTS,
    PROFILE_SCOPED_STRING_DEFAULTS,
    all_profile_keys,
)


def test_no_key_appears_in_more_than_one_registry() -> None:
    """A path cannot be registered as both numeric and string, etc."""
    numeric = set(PROFILE_SCOPED_DEFAULTS)
    string = set(PROFILE_SCOPED_STRING_DEFAULTS)
    dictv = set(PROFILE_SCOPED_DICT_DEFAULTS)
    assert numeric & string == set(), "key in both numeric + string registries"
    assert numeric & dictv == set(), "key in both numeric + dict registries"
    assert string & dictv == set(), "key in both string + dict registries"


def test_all_profile_keys_is_union() -> None:
    """all_profile_keys() returns the union of the three registries."""
    expected = (
        set(PROFILE_SCOPED_DEFAULTS)
        | set(PROFILE_SCOPED_STRING_DEFAULTS)
        | set(PROFILE_SCOPED_DICT_DEFAULTS)
    )
    assert all_profile_keys() == expected


def test_numeric_defaults_are_numeric() -> None:
    """PROFILE_SCOPED_DEFAULTS values must be int or float."""
    for key, value in PROFILE_SCOPED_DEFAULTS.items():
        assert isinstance(value, (int, float)), (
            f"non-numeric default for {key}: {value!r}"
        )


def test_string_defaults_are_strings() -> None:
    """PROFILE_SCOPED_STRING_DEFAULTS values must be str."""
    for key, value in PROFILE_SCOPED_STRING_DEFAULTS.items():
        assert isinstance(value, str), f"non-string default for {key}: {value!r}"


def test_dict_defaults_are_dicts() -> None:
    """PROFILE_SCOPED_DICT_DEFAULTS values must be dict."""
    for key, value in PROFILE_SCOPED_DICT_DEFAULTS.items():
        assert isinstance(value, dict), f"non-dict default for {key}: {value!r}"


def test_dotted_paths_are_valid_identifiers() -> None:
    """Every dotted path segment must be a valid identifier — no spaces / hyphens."""
    for key in all_profile_keys():
        for segment in key.split("."):
            assert segment.isidentifier(), (
                f"non-identifier segment {segment!r} in path {key!r}"
            )
