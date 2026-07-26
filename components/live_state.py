"""Per-browser-tab registry so a mutation on one page (approve a mod, reject media, etc.)
can refresh the shared UI surfaces that reflect the same state elsewhere -- the nav sidebar
badge, Home's attention chips/cards, and the Assistant's context card. Mirrors the
client-keyed pattern in components/ai_context.py: ui.refreshable closures are bound to one
client's DOM slots, so a global/unkeyed registry would try to refresh other clients' (or
disconnected clients') stale elements.
"""
from typing import Callable

from nicegui import context

_REGISTRY: dict[str, dict[str, Callable[[], None]]] = {}  # client_id -> {key: refresh_callable}


def register(key: str, refresh: Callable[[], None]) -> None:
    cid = context.client.id
    _REGISTRY.setdefault(cid, {})[key] = refresh


def refresh_all(exclude: str | None = None) -> None:
    for key, refresh in _REGISTRY.get(context.client.id, {}).items():
        if key == exclude:
            continue
        try:
            refresh()
        except Exception:
            pass
