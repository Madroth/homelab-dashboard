"""The one place this app reaches into media-curator.

`services/media.py` used to do `sys.path.append('/home/linuxbox/projects/media-curator')`
and then `from library import approve_item` at seven separate call sites, each inside a
function, each able to fail at runtime with a bare ImportError somewhere deep in a click
handler. There is no package boundary and no version pin, so a refactor over there breaks
this with no compile-time and no test-time signal.

That is not theoretical. media-curator's 2026-08-22 change to `queue.db` is what made an
IntegrityError reachable in `undo()`, which moved a file and then failed to record it --
filesystem and database permanently out of step, from a button press.

This module does not remove the coupling. Only media-curator publishing a real interface
can do that, and that is their Epic 7, not ours. What it does is make the coupling
**explicit, checkable, and loud**:

- Everything this app needs from over there is declared in one list, so the surface we
  depend on is readable in one place instead of inferred by grepping.
- `check()` reports what is missing without importing anything into the caller, following
  the same {'ok', ..., 'error'} contract as every reader in services/system.py.
- A missing symbol raises MediaBackendUnavailable naming the module, the symbol and the
  path searched -- so the failure says what broke and where, rather than "ImportError:
  cannot import name 'approve_item'".
"""
import importlib
import os
import sys

MEDIA_CURATOR_PATH = '/home/linuxbox/projects/media-curator'

# The complete surface this app borrows. If something new gets imported from over there,
# it belongs in this list -- that is the entire point of the list existing.
REQUIRED = {
    'database': ('get_conn',),
    'library': ('approve_item', 'reject_item'),
    'curator_daemon': ('identify_media', 'DROP_ZONE', 'is_contained'),
}


class MediaBackendUnavailable(RuntimeError):
    """Raised when media-curator does not provide something this app depends on."""


def _ensure_path() -> None:
    if MEDIA_CURATOR_PATH not in sys.path:
        sys.path.append(MEDIA_CURATOR_PATH)


def get(module_name: str, symbol: str):
    """Fetch one borrowed symbol, or fail with a message that says what is wrong.

    Deliberately not cached. media-curator is a live checkout that gets edited and
    reloaded independently of this process, and a cache would serve a symbol from before
    a refactor while reporting the world as fine.
    """
    declared = REQUIRED.get(module_name)
    if declared is None or symbol not in declared:
        # Catches drift in the other direction: code reaching for something the contract
        # never declared, which is how the surface silently grew to seven call sites.
        raise MediaBackendUnavailable(
            f'{module_name}.{symbol} is not declared in media_backend.REQUIRED. '
            f'Add it there first, so the surface this app depends on stays readable '
            f'in one place.')

    if not os.path.isdir(MEDIA_CURATOR_PATH):
        raise MediaBackendUnavailable(
            f'media-curator is not at {MEDIA_CURATOR_PATH}. This app imports its '
            f'internals directly over sys.path, so nothing media-related works without it.')

    _ensure_path()
    try:
        module = importlib.import_module(module_name)
    except Exception as e:
        raise MediaBackendUnavailable(
            f'could not import `{module_name}` from {MEDIA_CURATOR_PATH} '
            f'({type(e).__name__}: {e})') from e

    try:
        return getattr(module, symbol)
    except AttributeError as e:
        raise MediaBackendUnavailable(
            f'`{module_name}` no longer provides `{symbol}`. media-curator has changed '
            f'under this app -- see TODO.md "media-curator coupling".') from e


def check() -> dict:
    """Is every borrowed symbol still there? Reports rather than raises.

    Same shape as the readers in services/system.py, and for the same reason: "the
    backend is fine" and "we could not tell" have to be different answers.
    """
    if not os.path.isdir(MEDIA_CURATOR_PATH):
        return {'ok': False, 'missing': [], 'checked': 0,
                'error': f'media-curator is not at {MEDIA_CURATOR_PATH}'}

    missing, checked = [], 0
    for module_name, symbols in REQUIRED.items():
        for symbol in symbols:
            checked += 1
            try:
                get(module_name, symbol)
            except MediaBackendUnavailable as e:
                missing.append({'symbol': f'{module_name}.{symbol}', 'error': str(e)})

    return {'ok': not missing, 'missing': missing, 'checked': checked,
            'error': None if not missing
            else f'{len(missing)} of {checked} borrowed symbol(s) unavailable'}
