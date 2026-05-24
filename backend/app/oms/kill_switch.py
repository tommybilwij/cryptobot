"""KillSwitch — reads `oms.kill_switch_active` from the profile registry."""

from __future__ import annotations

from app.profile.params import ProfileParams


class KillSwitch:
    def __init__(self, *, params: ProfileParams) -> None:
        self._params = params

    def is_active(self) -> bool:
        return bool(self._params.get("oms.kill_switch_active"))
