"""ComponentGraveyard — in-memory set of deprecated scoring components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.runner_state import RunnerStateService

_GRAVEYARD_STATE_KEY = "component_graveyard"


@dataclass(frozen=True)
class GraveyardEntry:
    component: str
    reason: str


class ComponentGraveyard:
    def __init__(self, *, runner_state: RunnerStateService | None = None) -> None:
        self._buried: dict[str, GraveyardEntry] = {}
        self._runner_state = runner_state

    def add(self, component: str, reason: str) -> None:
        self._buried[component] = GraveyardEntry(component=component, reason=reason)

    def is_buried(self, component: str) -> bool:
        return component in self._buried

    def list(self) -> tuple[GraveyardEntry, ...]:
        return tuple(self._buried.values())

    def revive(self, component: str) -> None:
        self._buried.pop(component, None)

    async def persist(self) -> None:
        """Serialise buried entries to ``runner_state.component_graveyard``.

        No-op when no ``RunnerStateService`` was wired in.
        """
        if self._runner_state is None:
            return
        buried = [
            {"component": entry.component, "reason": entry.reason}
            for entry in self._buried.values()
        ]
        await self._runner_state.set(_GRAVEYARD_STATE_KEY, {"buried": buried})

    async def hydrate(self) -> None:
        """Repopulate from ``runner_state.component_graveyard``.

        Clears the in-memory set first so hydrate is idempotent. No-op when no
        service is wired in or no row exists yet.
        """
        if self._runner_state is None:
            return
        stored = await self._runner_state.get(_GRAVEYARD_STATE_KEY)
        if stored is None:
            return
        self._buried = {}
        for raw in stored.get("buried", []):
            component = str(raw["component"])
            self._buried[component] = GraveyardEntry(
                component=component,
                reason=str(raw["reason"]),
            )
