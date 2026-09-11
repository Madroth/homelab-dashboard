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


def send_article_to_plane(article: dict, summary: str, project_id: str | None = None) -> dict:
    """Creates a Plane issue from an article, then reads it back to confirm it exists.

    Returns {'created', 'verified', 'issue_id', 'already_existed', 'error'}. `created`
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

        body = summary or article.get('why_it_matters') or article.get('snippet') or ''
        source = article.get('source') or ''
        safe_body = html.escape(body).replace('\n', '<br/>')
        description_html = f"<p>{safe_body}</p>"
        if source:
            description_html += f'<p><a href="{html.escape(source)}">{html.escape(source)}</a></p>'

        payload = {'name': article['title'], 'description_html': description_html}
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
                        'error': 'Plane reports this article is already filed but did not '
                                 'return the issue id, so it could not be linked.'}
            return {'created': True, 'already_existed': True, 'issue_id': existing,
                    'error': None, 'project_id': project_id or PLANE_PROJECT_ID,
                    'verified': _issue_exists(existing, project_id)}
        resp.raise_for_status()
        issue_id = resp.json().get('id')
    except Exception as e:
        # Deliberately broader than RequestException: a malformed article (no title) or an
        # unreadable response raises something else entirely, and letting that escape kills
        # the caller's own error handling -- leaving its spinner running and saying nothing.
        return {'created': False, 'verified': False, 'issue_id': None,
                'already_existed': False, 'project_id': project_id or PLANE_PROJECT_ID,
                'error': f'{type(e).__name__}: {e}'}

    return {'created': True, 'already_existed': False, 'issue_id': issue_id, 'error': None,
            'project_id': project_id or PLANE_PROJECT_ID,
            'verified': _issue_exists(issue_id, project_id)}


def _issue_exists(issue_id: str | None, project_id: str | None = None) -> bool:
    """True if Plane can still hand back the issue we were just told it created."""
    return issue_status(issue_id, project_id) == 'present'


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
    if not issue_id:
        return 'gone'
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG,
                project_id or PLANE_PROJECT_ID]):
        return 'unknown'
    # The project matters as much as the id. This function is allowed to DELETE the
    # article's only link to its to-do when it reads 'gone', and an issue that lives in
    # another project answers 404 from the default one -- indistinguishable from deleted.
    # Asking the wrong project would orphan a live to-do and mark the article unsent.
    try:
        resp = requests.get(f"{_base_url(project_id)}/issues/{issue_id}/",
                            headers=_headers(), timeout=15)
    except requests.RequestException:
        return 'unknown'
    if resp.status_code == 404:
        return 'gone'
    if resp.status_code == 200:
        try:
            # A 200 carrying some other id is not an answer about this one -- don't act.
            return 'present' if resp.json().get('id') == issue_id else 'unknown'
        except ValueError:
            return 'unknown'
    return 'unknown'  # 401/403/5xx: Plane is not saying the issue is gone, only that it
                      # will not answer right now.
