from nicegui import context
from nicegui.client import Client


def capture_client() -> Client:
    """Grab a stable reference to the current client, independent of the UI slot stack.

    Call this at the very top of a row-triggered handler, before any refreshable.refresh()
    that might rebuild the row the click came from. NiceGUI runs the whole handler (all
    awaits included) inside the slot the click event captured at dispatch time -- if the
    handler itself later destroys that slot (e.g. render_articles.refresh() tearing down and
    rebuilding the clicked row), context.client stops resolving for the *rest* of that same
    handler, not just for other code: `context.client` walks up through `context.slot.parent`,
    and once that parent element is gone it raises RuntimeError, which client_alive() then
    (wrongly) reports as "client disconnected" even though the browser tab is still there.
    Passing the client captured here into client_alive() sidesteps that lookup entirely.
    """
    return context.client


def client_alive(client: Client | None = None) -> bool:
    """True unless the browser tab that owns the given (or current) UI context has
    disconnected.

    Guards refreshable-refresh calls after an `await run.io_bound(...)` gap, since the
    client can vanish mid-await (tab closed) and a refresh against a deleted client raises.
    Pass a `client` captured early via `capture_client()` when the handler may have torn down
    its own originating slot by the time this is called (see that function's docstring) --
    otherwise this falls back to resolving `context.client` fresh, which itself can raise
    RuntimeError (not just report is_deleted=True) once the slot's parent element has already
    been torn down, so that counts as "not alive" too.
    """
    if client is not None:
        return not client.is_deleted
    try:
        return not context.client.is_deleted
    except RuntimeError:
        return False
