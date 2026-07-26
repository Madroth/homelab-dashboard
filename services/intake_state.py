"""Dashboard-owned per-article workflow state (read/favorite/archived), user-created
folders, view/sort prefs, and per-article Discuss conversation threads. Kept separate
from homelab-intake's article markdown files -- this is pure UI/workflow state, not
content, so it doesn't belong in the pipeline's frontmatter (see services/intake.py's
`user_folders`, which IS content metadata and does live in frontmatter).

Plain JSON with atomic writes (temp file + os.replace), not SQLite: single writer (this
process), no concurrent daemon, no relational queries -- just per-article key lookups
and occasional bulk updates. Mirrors the precedent already set by services/settings.py.
"""
import json
import os
import tempfile

STATE_FILE = os.path.expanduser('~/projects/homelab-dashboard/intake_state.json')
CONVERSATIONS_FILE = os.path.expanduser('~/projects/homelab-dashboard/intake_conversations.json')

_DEFAULT_ARTICLE_STATE = {'read': False, 'favorite': False, 'archived': False}
_DEFAULT_STATE = {'articles': {}, 'folders': [], 'prefs': {'view': 'cards', 'sort': 'date'}}


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


def _load_state() -> dict:
    state = _load(STATE_FILE, _DEFAULT_STATE)
    state.setdefault('articles', {})
    state.setdefault('folders', [])
    state.setdefault('prefs', {'view': 'cards', 'sort': 'date'})
    return state


def get_article_state(article_id: str) -> dict:
    return _load_state()['articles'].get(article_id, dict(_DEFAULT_ARTICLE_STATE))


def all_article_states() -> dict:
    return _load_state()['articles']


def set_article_state(article_id: str, **fields) -> None:
    state = _load_state()
    current = state['articles'].get(article_id, dict(_DEFAULT_ARTICLE_STATE))
    current.update(fields)
    state['articles'][article_id] = current
    _atomic_write(STATE_FILE, state)


def bulk_set_article_state(article_ids: list[str], **fields) -> None:
    state = _load_state()
    for aid in article_ids:
        current = state['articles'].get(aid, dict(_DEFAULT_ARTICLE_STATE))
        current.update(fields)
        state['articles'][aid] = current
    _atomic_write(STATE_FILE, state)


def list_folders() -> list[str]:
    return _load_state()['folders']


def create_folder(name: str) -> None:
    state = _load_state()
    if name and name not in state['folders']:
        state['folders'].append(name)
        _atomic_write(STATE_FILE, state)


def get_prefs() -> dict:
    return _load_state()['prefs']


def set_prefs(**fields) -> None:
    state = _load_state()
    state['prefs'].update(fields)
    _atomic_write(STATE_FILE, state)


# --- Discuss conversation threads ---

def _load_conversations() -> dict:
    return _load(CONVERSATIONS_FILE, {})


def get_thread(article_id: str) -> list[dict]:
    return _load_conversations().get(article_id, [])


def append_message(article_id: str, message: dict) -> None:
    convos = _load_conversations()
    convos.setdefault(article_id, []).append(message)
    _atomic_write(CONVERSATIONS_FILE, convos)


def clear_thread(article_id: str) -> None:
    convos = _load_conversations()
    if article_id in convos:
        del convos[article_id]
        _atomic_write(CONVERSATIONS_FILE, convos)


def thread_counts() -> dict:
    """{article_id: message_count}, for the chat-bubble chip on list rows."""
    return {aid: len(msgs) for aid, msgs in _load_conversations().items()}
