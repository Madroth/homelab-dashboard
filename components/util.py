from nicegui import context


def client_alive() -> bool:
    """True unless the browser tab that owns the current UI context has disconnected.

    Guards refreshable-refresh calls after an `await run.io_bound(...)` gap, since the
    client can vanish mid-await (tab closed) and a refresh against a deleted client raises.
    `context.client` itself can raise RuntimeError (not just report is_deleted=True) once the
    slot's parent element has already been torn down, so that counts as "not alive" too.
    """
    try:
        return not context.client.is_deleted
    except RuntimeError:
        return False
