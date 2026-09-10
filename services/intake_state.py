"""Dashboard-owned per-article workflow state (read/favorite/archived), user-created
folders, view/sort prefs, and per-article Discuss conversation threads. Kept separate
from homelab-intake's article markdown files -- this is pure UI/workflow state, not
content, so it doesn't belong in the pipeline's frontmatter (see services/intake.py's
`user_folders`, which IS content metadata and does live in frontmatter).

Plain JSON with atomic writes (temp file + os.replace), not SQLite: single writer (this
process), no concurrent daemon, no relational queries -- just per-article key lookups
and occasional bulk updates. Mirrors the precedent already set by services/settings.py.
"""
import contextlib
import fcntl
import json
import os
import tempfile

STATE_FILE = os.path.expanduser('~/projects/homelab-dashboard/intake_state.json')
CONVERSATIONS_FILE = os.path.expanduser('~/projects/homelab-dashboard/intake_conversations.json')

# plane_issue_id doubles as the 'already sent' flag -- holding the id rather than a
# bare bool means a sent article can be traced back to its actual to-do.
#
# plane_project_id records WHERE that to-do lives, and is not optional once a project
# picker exists. plane.issue_status() is allowed to clear plane_issue_id when it reads
# 'gone', and an issue in another project answers 404 from the default one -- which is
# indistinguishable from deleted. Without this field, re-checking an article sent to a
# non-default project would orphan a live to-do and mark the article unsent. None means
# "sent before the picker existed", which resolves to the configured default.
_DEFAULT_ARTICLE_STATE = {'read': False, 'favorite': False, 'archived': False,
                          'plane_issue_id': None, 'plane_project_id': None}
_DEFAULT_STATE = {'articles': {}, 'folders': [], 'prefs': {'density': 'cozy', 'sort': 'unread'}}
_DEFAULT_SOURCES = {'archive': True, 'repos': []}
DEFAULT_MODEL = 'claude'  # per-article picks (see get_model/set_model) override this


@contextlib.contextmanager
def _file_lock(path: str):
    """Advisory lock guarding a read-modify-write cycle on `path`. Needed once multiple
    browser tabs are in play (the accepted trade-off behind pages/intake.py's in-memory
    workflow patching): each read-modify-write here re-reads the whole file fresh from
    disk, so two near-simultaneous writes from different tabs could otherwise silently
    drop one of them -- same race class as services/intake.py's queue.json lock."""
    lock_path = path + '.lock'
    with open(lock_path, 'w') as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def _atomic_write(path: str, data) -> None:
    d = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=d, prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _load(path: str, default):
    if not os.path.exists(path):
        return json.loads(json.dumps(default))
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))


def _normalize_prefs(prefs: dict) -> dict:
    """Migrates the pre-2026-07-31 shape ({'view': 'cards'|'table', ...}) to the
    current one ({'density': 'cozy'|'compact', ...}) -- table view no longer exists,
    so it maps to 'compact' (closest equivalent, dense single-column); cards maps to
    'cozy'. A file already on the new shape (or with neither key) is left alone."""
    prefs = dict(prefs)
    if 'density' not in prefs:
        old_view = prefs.pop('view', None)
        prefs['density'] = 'compact' if old_view == 'table' else 'cozy'
    prefs.setdefault('sort', 'unread')
    return prefs


def _load_state() -> dict:
    state = _load(STATE_FILE, _DEFAULT_STATE)
    state.setdefault('articles', {})
    state.setdefault('folders', [])
    state['prefs'] = _normalize_prefs(state.get('prefs') or {})
    return state


def get_article_state(article_id: str) -> dict:
    return _load_state()['articles'].get(article_id, dict(_DEFAULT_ARTICLE_STATE))


def all_article_states() -> dict:
    return _load_state()['articles']


def set_article_state(article_id: str, **fields) -> None:
    with _file_lock(STATE_FILE):
        state = _load_state()
        current = state['articles'].get(article_id, dict(_DEFAULT_ARTICLE_STATE))
        current.update(fields)
        state['articles'][article_id] = current
        _atomic_write(STATE_FILE, state)


def bulk_set_article_state(article_ids: list[str], **fields) -> None:
    with _file_lock(STATE_FILE):
        state = _load_state()
        for aid in article_ids:
            current = state['articles'].get(aid, dict(_DEFAULT_ARTICLE_STATE))
            current.update(fields)
            state['articles'][aid] = current
        _atomic_write(STATE_FILE, state)


def list_folders() -> list[str]:
    return _load_state()['folders']


def create_folder(name: str) -> None:
    with _file_lock(STATE_FILE):
        state = _load_state()
        if name and name not in state['folders']:
            state['folders'].append(name)
            _atomic_write(STATE_FILE, state)


def get_prefs() -> dict:
    return _load_state()['prefs']


def set_prefs(**fields) -> None:
    with _file_lock(STATE_FILE):
        state = _load_state()
        state['prefs'].update(fields)
        _atomic_write(STATE_FILE, state)


# --- Discuss conversation threads + per-conversation grounding scope ---
#
# Shape: {article_id: {"messages": [...], "sources": {"archive": bool, "repos": [str]}}}.
# Older files may still have the pre-migration shape ({article_id: [messages]}) --
# _normalize_conversation() upgrades an entry in memory on read; every write goes out
# in the new shape, so the file self-migrates the first time each article's entry is
# touched again. `sources` doesn't track "article" -- that source is always on and
# isn't a user choice (see components/discuss_panel.py).

def _normalize_conversation(entry) -> dict:
    if isinstance(entry, list):
        return {'messages': entry, 'sources': dict(_DEFAULT_SOURCES), 'model': None}
    entry = dict(entry)
    entry.setdefault('messages', [])
    entry.setdefault('sources', dict(_DEFAULT_SOURCES))
    entry.setdefault('model', None)  # None -> DEFAULT_MODEL (no explicit pick yet)
    return entry


def _load_conversations() -> dict:
    return _load(CONVERSATIONS_FILE, {})


def get_thread(article_id: str) -> list[dict]:
    convos = _load_conversations()
    if article_id not in convos:
        return []
    return _normalize_conversation(convos[article_id])['messages']


def append_message(article_id: str, message: dict) -> None:
    with _file_lock(CONVERSATIONS_FILE):
        convos = _load_conversations()
        entry = _normalize_conversation(convos.get(article_id, {}))
        entry['messages'].append(message)
        convos[article_id] = entry
        _atomic_write(CONVERSATIONS_FILE, convos)


def clear_thread(article_id: str) -> None:
    """Empties the article's messages but keeps its model pick and source toggles --
    'Clear' means start the conversation over, not re-do the setup choices
    (Chris, 2026-08-04: model/sources must stay stuck to the article)."""
    with _file_lock(CONVERSATIONS_FILE):
        convos = _load_conversations()
        if article_id in convos:
            entry = _normalize_conversation(convos[article_id])
            entry['messages'] = []
            convos[article_id] = entry
            _atomic_write(CONVERSATIONS_FILE, convos)


def thread_counts() -> dict:
    """{article_id: message_count}, for the chat-bubble chip on list rows."""
    return {aid: len(_normalize_conversation(entry)['messages'])
            for aid, entry in _load_conversations().items()}


def get_sources(article_id: str) -> dict:
    convos = _load_conversations()
    if article_id not in convos:
        return dict(_DEFAULT_SOURCES)
    return _normalize_conversation(convos[article_id])['sources']


def set_sources(article_id: str, **fields) -> None:
    with _file_lock(CONVERSATIONS_FILE):
        convos = _load_conversations()
        entry = _normalize_conversation(convos.get(article_id, {}))
        entry['sources'].update(fields)
        convos[article_id] = entry
        _atomic_write(CONVERSATIONS_FILE, convos)


def get_model(article_id: str) -> str:
    convos = _load_conversations()
    if article_id not in convos:
        return DEFAULT_MODEL
    return _normalize_conversation(convos[article_id])['model'] or DEFAULT_MODEL


def set_model(article_id: str, model: str) -> None:
    with _file_lock(CONVERSATIONS_FILE):
        convos = _load_conversations()
        entry = _normalize_conversation(convos.get(article_id, {}))
        entry['model'] = model
        convos[article_id] = entry
        _atomic_write(CONVERSATIONS_FILE, convos)
