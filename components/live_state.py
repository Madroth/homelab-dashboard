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
    client = context.client
    cid = client.id
    if cid not in _REGISTRY:
        # Forget the tab when NiceGUI discards it. Nothing did, so every page view left its
        # refresh closures -- and through them its whole element tree -- here until the
        # service restarted (AntiGravity's review, 2026-09-11). No-argument closure on
        # purpose: NiceGUI passes the client to a handler that takes a parameter.
        client.on_delete(lambda: _REGISTRY.pop(cid, None))
    _REGISTRY.setdefault(cid, {})[key] = refresh


def refresh_all(exclude: str | None = None, client=None) -> None:
    """Pass `client` (captured early via components.util.capture_client()) when the
    caller may have already torn down its own originating UI slot by this point (e.g.
    a row handler that called its own refreshable.refresh() first) -- context.client
    re-resolves via that slot on every access, so once it's gone this would otherwise
    raise RuntimeError instead of just finding no client_id to look up.
    """
    try:
        cid = client.id if client is not None else context.client.id
    except RuntimeError:
        return
    for key, refresh in _REGISTRY.get(cid, {}).items():
        if key == exclude:
            continue
        try:
            # The registered callables create a ui.timer, which needs a live slot. From a
            # handler whose own row is gone, the ambient one is dead -- and the exception
            # below used to swallow that, so the other pages silently never refreshed.
            if client is not None:
                with client:
                    refresh()
            else:
                refresh()
        except Exception:
            pass
