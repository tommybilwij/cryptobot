"""WalletRotator — picks the active sub-account name from the registry.

Phase 11 contract: each venue/strategy ships with two API-key slots
(``..._a`` and ``..._b``) in ``Settings``. The active slot is selected by
``wallet.active_suffix`` in the profile registry — flipping it from ``"a"``
to ``"b"`` rotates which env-key gets loaded by the exchange factory next
restart, allowing zero-downtime key rolls without code edits.

This service is purely the name-derivation layer: it knows how to compose
``{base_sub_account}_{suffix}`` but does not load credentials itself. The
exchange factory consumes the derived name to look up the matching
``binance_api_key_<derived_name>`` field on ``Settings``.
"""

from __future__ import annotations

from app.profile.params import ProfileParams


class WalletRotator:
    """Derive the active sub-account name for a strategy.

    Construct once per strategy with the strategy's ``ProfileParams`` and
    call ``active_sub_account(base)`` whenever the credential lookup runs.
    The rotator re-reads the registry on every call so a hot profile-apply
    takes effect on the next tick without recreating the rotator.
    """

    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def active_sub_account(self, base_sub_account: str | None) -> str | None:
        """Return ``{base}_{suffix}`` if rotation is active, else ``base``.

        Passing ``None`` propagates ``None`` — the strategy has no
        sub-account configured and the caller should fall back to the
        venue's master key.
        """
        if base_sub_account is None:
            return None
        suffix = str(self._params.get("wallet.active_suffix"))
        if suffix:
            return f"{base_sub_account}_{suffix}"
        return base_sub_account
