"""'Send to HomeLab' — creates a Plane to-do from an article. Mirrors the request
pattern already proven by ~/projects/github-plane-sync/sync.py (same workspace/project,
same X-Api-Key auth, same description_html field), rather than inventing a new one.
"""
import hashlib
import html
import os

import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/projects/homelab-dashboard/.env'))

PLANE_API_KEY = os.getenv('PLANE_API_KEY')
PLANE_API_URL = os.getenv('PLANE_API_URL')
PLANE_WORKSPACE_SLUG = os.getenv('PLANE_WORKSPACE_SLUG')
PLANE_PROJECT_ID = os.getenv('PLANE_PROJECT_ID')
PLANE_ARTICLE_LABEL = os.getenv('PLANE_ARTICLE_LABEL', 'from-article')
EXTERNAL_SOURCE = 'homelab-intake'  # paired with the article id as Plane's external_id


def _base_url(project_id: str | None = None) -> str:
    return (f"{PLANE_API_URL}/workspaces/{PLANE_WORKSPACE_SLUG}"
            f"/projects/{project_id or PLANE_PROJECT_ID}")


def list_projects() -> dict:
    """Every project this API key can see, for choosing where a to-do lands.

    Fail-closed like the readers in services/system.py: an empty list because Plane did
    not answer must not look like a workspace with no projects, or the picker silently
    offers nothing and the user concludes there is nowhere to send.
    """
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG]):
        return {'ok': False, 'projects': [], 'default_id': PLANE_PROJECT_ID,
                'error': 'Plane is not configured (missing values in homelab-dashboard/.env).'}
    try:
        resp = requests.get(f"{PLANE_API_URL}/workspaces/{PLANE_WORKSPACE_SLUG}/projects/",
                            headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('results', data) if isinstance(data, dict) else data
    except (requests.RequestException, ValueError) as e:
        return {'ok': False, 'projects': [], 'default_id': PLANE_PROJECT_ID,
                'error': f'{type(e).__name__}: {e}'}

    projects = [{'id': p.get('id'), 'name': p.get('name') or p.get('identifier') or p.get('id')}
                for p in items if p.get('id')]
    projects.sort(key=lambda p: (p['id'] != PLANE_PROJECT_ID, p['name'].lower()))
    return {'ok': True, 'projects': projects, 'default_id': PLANE_PROJECT_ID, 'error': None}


def _headers() -> dict:
    return {'X-Api-Key': PLANE_API_KEY, 'Content-Type': 'application/json'}


def _get_or_create_label(project_id: str | None = None) -> str | None:
    """Returns the Plane label ID for PLANE_ARTICLE_LABEL, creating it if missing.

    Returns None -- leaving the issue unlabelled -- if the label endpoints are not
    reachable. An API key whose user is not a member of the project is workspace-scoped:
    Plane answers 403 on /labels/ while still accepting the issue POST. Labelling is a
    nicety and must not be able to lose the to-do itself.
    """
    try:
        resp = requests.get(f"{_base_url(project_id)}/labels/", headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        labels = data.get('results', data) if isinstance(data, dict) else data
        for label in labels:
            if label.get('name') == PLANE_ARTICLE_LABEL:
                return label['id']

        resp = requests.post(f"{_base_url(project_id)}/labels/", headers=_headers(),
                              json={'name': PLANE_ARTICLE_LABEL, 'color': '#cba6f7'}, timeout=15)
        resp.raise_for_status()
        return resp.json().get('id')
    except requests.RequestException:
        return None


def _describe(article: dict, summary: str) -> tuple[str, str]:
    """The to-do's name and description for an article -- one builder, so a send and a
    later update cannot drift into writing different shapes."""
    body = summary or article.get('why_it_matters') or article.get('snippet') or ''
    source = article.get('source') or ''
    safe_body = html.escape(body).replace('\n', '<br/>')
    description_html = f"<p>{safe_body}</p>"
    if source:
        description_html += f'<p><a href="{html.escape(source)}">{html.escape(source)}</a></p>'
    return article['title'], description_html


def _sha(*parts) -> str:
    return hashlib.sha256('\0'.join(p or '' for p in parts).encode()).hexdigest()


def _held(issue: dict) -> str:
    """Fingerprint of the two fields an update may overwrite, AS PLANE STORES THEM.

    Not as we sent them: Plane rewrites description_html on save (a `<p>` sent comes back
    wrapped in `<div>`, observed 2026-09-11), so comparing against what we sent would read
    every to-do as hand-edited and no update would ever be allowed to refresh one.
    """
    return _sha(issue.get('name'), issue.get('description_html'))


def send_article_to_plane(article: dict, summary: str, project_id: str | None = None) -> dict:
    """Creates a Plane issue from an article, then reads it back to confirm it exists.

    Returns {'created', 'verified', 'issue_id', 'already_existed', 'fingerprint', 'error'}.
    `fingerprint` is what update_article_todo() later needs to tell whether the to-do has
    been edited in Plane since; None whenever this call cannot vouch for that. `created`
    means Plane holds an issue for this article; `verified` means a follow-up GET found it
    actually there. They are reported separately on purpose: a read-back that fails after a
    successful create must not be mistaken for "not sent", or the caller retries and files
    a duplicate.

    The article's id is sent as Plane's `external_id`, which makes a resend idempotent at
    the server: Plane answers a repeat with 409 and hands back the id of the issue it
    already has, so a retry after a lost response recovers that issue instead of creating
    a second one. That is the only defence against a create whose reply never arrived --
    local state cannot know the difference.
    """
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG,
                project_id or PLANE_PROJECT_ID]):
        return {'created': False, 'verified': False, 'issue_id': None, 'already_existed': False,
                'project_id': project_id or PLANE_PROJECT_ID,
                'error': 'Plane is not configured (missing values in homelab-dashboard/.env).'}

    try:
        label_id = _get_or_create_label(project_id)
        name, description_html = _describe(article, summary)
        payload = {'name': name, 'description_html': description_html}
        # The external_id is the ONLY thing standing between a lost response and a
        # duplicate to-do, so it is never optional. An article with no id used to send
        # without one, quietly dropping back to the un-idempotent behaviour this exists
        # to prevent -- derive a stable key from the content instead.
        external_id = str(article.get('id') or '').strip()
        if not external_id:
            digest = hashlib.sha1(
                f"{article['title']}|{article.get('source') or ''}".encode()).hexdigest()
            external_id = f'sha1:{digest}'
        payload['external_id'] = external_id
        payload['external_source'] = EXTERNAL_SOURCE
        if label_id:
            payload['labels'] = [label_id]

        resp = requests.post(f"{_base_url(project_id)}/issues/", headers=_headers(),
                             json=payload, timeout=30)
        if resp.status_code == 409:
            # Already filed under this external_id; the 409 body carries the existing id.
            try:
                existing = resp.json().get('id')
            except ValueError:
                existing = None
            if not existing:
                # Plane says the id is taken but not by which issue. Recording nothing
                # would leave the article un-ticked and retrying into the same 409
                # forever, so report it as a real outcome rather than a silent link.
                return {'created': True, 'already_existed': True, 'issue_id': None,
                        'verified': False, 'project_id': project_id or PLANE_PROJECT_ID,
                        'fingerprint': None,
                        'error': 'Plane reports this article is already filed but did not '
                                 'return the issue id, so it could not be linked.'}
            # No fingerprint: this call did not write that issue, and nothing here knows
            # whether someone has edited it since. An update will add a comment instead.
            return {'created': True, 'already_existed': True, 'issue_id': existing,
                    'error': None, 'project_id': project_id or PLANE_PROJECT_ID,
                    'fingerprint': None,
                    'verified': issue_status(existing, project_id) == 'present'}
        resp.raise_for_status()
        issue_id = resp.json().get('id')
    except Exception as e:
        # Deliberately broader than RequestException: a malformed article (no title) or an
        # unreadable response raises something else entirely, and letting that escape kills
        # the caller's own error handling -- leaving its spinner running and saying nothing.
        return {'created': False, 'verified': False, 'issue_id': None,
                'already_existed': False, 'project_id': project_id or PLANE_PROJECT_ID,
                'fingerprint': None, 'error': f'{type(e).__name__}: {e}'}

    # The read-back doubles as the fingerprint: what Plane actually stored, right after we
    # wrote it. Without a successful read-back there is nothing to vouch for.
    status, issue = _fetch_issue(issue_id, project_id)
    verified = status == 'present'
    return {'created': True, 'already_existed': False, 'issue_id': issue_id, 'error': None,
            'project_id': project_id or PLANE_PROJECT_ID, 'verified': verified,
            'fingerprint': ({'sent': _sha(name, description_html), 'held': _held(issue)}
                            if verified else None)}


UPDATE_NOTE_HTML = {
    'edited': ('<p><em>The article behind this to-do was updated in homelab-intake. The to-do '
               'had been edited here since the dashboard last wrote it, so this is added as a '
               'comment rather than replacing anything.</em></p>'),
    'untracked': ('<p><em>The article behind this to-do was updated in homelab-intake. The '
                  'dashboard cannot tell whether this to-do has been edited here, so this is '
                  'added as a comment rather than replacing anything.</em></p>'),
}


def update_article_todo(article: dict, summary: str, issue_id: str,
                        project_id: str | None = None, fingerprint: dict | None = None) -> dict:
    """Brings a sent to-do up to date with its article, never overwriting a hand edit.

    Chris's call, 2026-09-11: refresh the to-do's name and description, but only if Plane
    still holds exactly what the dashboard last wrote there. If anyone has edited either
    field in Plane since -- or the to-do predates fingerprints, so nobody can say -- the
    update is posted as a comment instead. State, labels, assignees and comments are never
    touched either way.

    `fingerprint` is {'sent', 'held'} as recorded by the last successful write: `sent` the
    content we last pushed (so an unchanged article is a no-op rather than a duplicate
    comment), `held` what Plane stored afterwards (see _held()).

    Returns {'outcome', 'fingerprint', 'error'} (+ 'reason' when commented), outcome one of:
      'refreshed'  name + description replaced
      'commented'  the update went in as a comment -- reason 'edited' (Plane was changed
                   since our write) or 'untracked' (no fingerprint, so nobody can say)
      'unchanged'  nothing new since the last write; nothing sent
      'gone'       Plane answered 404 -- the caller may clear the link, as issue_status()
      'unknown'    Plane did not answer; nothing was changed
      'failed'     a write failed; the stored fingerprint is returned unchanged

    A window remains between the read and the PATCH in which a hand edit could land; Plane
    offers no conditional write to close it. It is the width of one request.
    """
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG,
                project_id or PLANE_PROJECT_ID]):
        return {'outcome': 'unknown', 'fingerprint': fingerprint,
                'error': 'Plane is not configured (missing values in homelab-dashboard/.env).'}
    try:
        name, description_html = _describe(article, summary)
        sent = _sha(name, description_html)
        status, issue = _fetch_issue(issue_id, project_id)
        if status == 'gone':
            return {'outcome': 'gone', 'fingerprint': None, 'error': None}
        if status != 'present':
            return {'outcome': 'unknown', 'fingerprint': fingerprint,
                    'error': 'HomeLab did not answer, so nothing was changed.'}
        if fingerprint and fingerprint.get('sent') == sent:
            return {'outcome': 'unchanged', 'fingerprint': fingerprint, 'error': None}

        if fingerprint and fingerprint.get('held') == _held(issue):
            resp = requests.patch(f"{_base_url(project_id)}/issues/{issue_id}/",
                                  headers=_headers(), timeout=30,
                                  json={'name': name, 'description_html': description_html})
            resp.raise_for_status()
            status, issue = _fetch_issue(issue_id, project_id)
            if status != 'present':
                # Written, but unconfirmed -- so no fingerprint to vouch for, and the next
                # update will comment rather than risk overwriting.
                return {'outcome': 'refreshed', 'fingerprint': {'sent': sent, 'held': None},
                        'error': 'Updated, but the to-do could not be read back to confirm it.'}
            return {'outcome': 'refreshed', 'fingerprint': {'sent': sent, 'held': _held(issue)},
                    'error': None}

        reason = 'edited' if (fingerprint or {}).get('held') else 'untracked'
        resp = requests.post(f"{_base_url(project_id)}/issues/{issue_id}/comments/",
                             headers=_headers(), timeout=30,
                             json={'comment_html': UPDATE_NOTE_HTML[reason] + description_html})
        resp.raise_for_status()
        # `held` deliberately stays as it was. Recording the hand-edited version as ours
        # would let the NEXT update overwrite it.
        return {'outcome': 'commented', 'reason': reason, 'error': None,
                'fingerprint': {'sent': sent, 'held': (fingerprint or {}).get('held')}}
    except Exception as e:  # noqa: BLE001 -- same reasoning as send_article_to_plane
        return {'outcome': 'failed', 'fingerprint': fingerprint,
                'error': f'{type(e).__name__}: {e}'}


def issue_status(issue_id: str | None, project_id: str | None = None) -> str:
    """'present' | 'gone' | 'unknown' for an issue id we recorded earlier.

    Deliberately three-valued rather than a bool. Confirming a create can collapse
    everything that is not a 200 into "not confirmed" safely -- the worst case there is an
    id recorded without a tick. Reconciling cannot: it acts on the answer by *deleting*
    the article's only link to its to-do, so reading a timeout or a 502 as "deleted" would
    throw away a live to-do every time Plane restarts. Only a 404 -- Plane positively
    stating it has no such issue -- is allowed to mean gone; everything else is unknown
    and changes nothing.
    """
    return _fetch_issue(issue_id, project_id)[0]


def _fetch_issue(issue_id: str | None, project_id: str | None = None) -> tuple[str, dict | None]:
    """issue_status() with the issue attached when it is 'present'. Same rules."""
    if not issue_id:
        return 'gone', None
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG,
                project_id or PLANE_PROJECT_ID]):
        return 'unknown', None
    # The project matters as much as the id. A 'gone' from here is allowed to DELETE the
    # article's only link to its to-do, and an issue that lives in
    # another project answers 404 from the default one -- indistinguishable from deleted.
    # Asking the wrong project would orphan a live to-do and mark the article unsent.
    try:
        resp = requests.get(f"{_base_url(project_id)}/issues/{issue_id}/",
                            headers=_headers(), timeout=15)
    except requests.RequestException:
        return 'unknown', None
    if resp.status_code == 404:
        return 'gone', None
    if resp.status_code == 200:
        try:
            issue = resp.json()
        except ValueError:
            return 'unknown', None
        # A 200 carrying some other id is not an answer about this one -- don't act.
        return ('present', issue) if issue.get('id') == issue_id else ('unknown', None)
    return 'unknown', None  # 401/403/5xx: Plane is not saying the issue is gone, only
                            # that it will not answer right now.
