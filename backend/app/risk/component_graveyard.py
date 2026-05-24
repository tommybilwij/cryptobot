"""ComponentGraveyard — in-memory set of deprecated scoring components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GraveyardEntry:
    component: str
    reason: str


class ComponentGraveyard:
    def __init__(self) -> None:
        self._buried: dict[str, GraveyardEntry] = {}

    def add(self, component: str, reason: str) -> None:
        self._buried[component] = GraveyardEntry(component=component, reason=reason)

    def is_buried(self, component: str) -> bool:
        return component in self._buried

    def list(self) -> tuple[GraveyardEntry, ...]:
        return tuple(self._buried.values())

    def revive(self, component: str) -> None:
        self._buried.pop(component, None)
