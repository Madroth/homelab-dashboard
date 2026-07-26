"""Per-browser-tab registry of "what's currently on screen", so the AI Assistant sidebar
can ground its answers in whatever the user is actually looking at instead of just the
raw chat history. Each page registers a summary function once at build() time; layout.py
updates which tab is active on every switch; the chat sidebar reads it fresh on every send.
"""
from typing import Callable

from nicegui import context

_REGISTRY: dict[str, dict] = {}  # client_id -> {'active_tab': str, 'getters': {}, 'card_getters': {}}


def _entry() -> dict:
    cid = context.client.id
    return _REGISTRY.setdefault(cid, {'active_tab': None, 'getters': {}, 'card_getters': {}})


def register(tab_key: str, get_summary: Callable[[], str]) -> None:
    _entry()['getters'][tab_key] = get_summary


def register_card(tab_key: str, get_card: Callable[[], dict]) -> None:
    """get_card() returns {'icon': str, 'tab': str, 'pills': list[str], 'focus': str} for the
    Assistant panel's "Seeing your current tab" card. Should derive from the same per-page
    state snapshot as the tab's register()'d text summary, not duplicate its own logic."""
    _entry()['card_getters'][tab_key] = get_card


def set_active_tab(tab_key: str) -> None:
    _entry()['active_tab'] = tab_key


def active_tab() -> str | None:
    return _REGISTRY.get(context.client.id, {}).get('active_tab')


def current_context_text() -> str:
    entry = _REGISTRY.get(context.client.id)
    if not entry or not entry['active_tab']:
        return ''
    getter = entry['getters'].get(entry['active_tab'])
    if not getter:
        return ''
    try:
        return getter()
    except Exception:
        return ''


def current_context_card() -> dict | None:
    entry = _REGISTRY.get(context.client.id)
    if not entry or not entry['active_tab']:
        return None
    getter = entry['card_getters'].get(entry['active_tab'])
    if not getter:
        return None
    try:
        return getter()
    except Exception:
        return None
