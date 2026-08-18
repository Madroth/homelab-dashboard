"""'Send to HomeLab' — creates a Plane to-do from an article. Mirrors the request
pattern already proven by ~/projects/github-plane-sync/sync.py (same workspace/project,
same X-Api-Key auth, same description_html field), rather than inventing a new one.
"""
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


def _base_url() -> str:
    return f"{PLANE_API_URL}/workspaces/{PLANE_WORKSPACE_SLUG}/projects/{PLANE_PROJECT_ID}"


def _headers() -> dict:
    return {'X-Api-Key': PLANE_API_KEY, 'Content-Type': 'application/json'}


def _get_or_create_label() -> str | None:
    """Returns the Plane label ID for PLANE_ARTICLE_LABEL, creating it if missing.

    Returns None -- leaving the issue unlabelled -- if the label endpoints are not
    reachable. An API key whose user is not a member of the project is workspace-scoped:
    Plane answers 403 on /labels/ while still accepting the issue POST. Labelling is a
    nicety and must not be able to lose the to-do itself.
    """
    try:
        resp = requests.get(f"{_base_url()}/labels/", headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        labels = data.get('results', data) if isinstance(data, dict) else data
        for label in labels:
            if label.get('name') == PLANE_ARTICLE_LABEL:
                return label['id']

        resp = requests.post(f"{_base_url()}/labels/", headers=_headers(),
                              json={'name': PLANE_ARTICLE_LABEL, 'color': '#cba6f7'}, timeout=15)
        resp.raise_for_status()
        return resp.json().get('id')
    except requests.RequestException:
        return None


def send_article_to_plane(article: dict, summary: str) -> dict:
    """Creates a Plane issue from an article, then reads it back to confirm it exists.

    Returns {'created', 'verified', 'issue_id', 'error'}. `created` means Plane accepted
    the POST; `verified` means a follow-up GET found the issue actually there. They are
    reported separately on purpose: a read-back that fails after a successful create must
    not be mistaken for "not sent", or the caller retries and files a duplicate.
    """
    if not all([PLANE_API_KEY, PLANE_API_URL, PLANE_WORKSPACE_SLUG, PLANE_PROJECT_ID]):
        return {'created': False, 'verified': False, 'issue_id': None,
                'error': 'Plane is not configured (missing values in homelab-dashboard/.env).'}

    try:
        label_id = _get_or_create_label()

        body = summary or article.get('why_it_matters') or article.get('snippet') or ''
        source = article.get('source') or ''
        safe_body = html.escape(body).replace('\n', '<br/>')
        description_html = f"<p>{safe_body}</p>"
        if source:
            description_html += f'<p><a href="{html.escape(source)}">{html.escape(source)}</a></p>'

        payload = {'name': article['title'], 'description_html': description_html}
        if label_id:
            payload['labels'] = [label_id]

        resp = requests.post(f"{_base_url()}/issues/", headers=_headers(), json=payload, timeout=30)
        resp.raise_for_status()
        issue_id = resp.json().get('id')
    except requests.RequestException as e:
        return {'created': False, 'verified': False, 'issue_id': None, 'error': str(e)}

    return {'created': True, 'issue_id': issue_id, 'error': None,
            'verified': _issue_exists(issue_id)}


def _issue_exists(issue_id: str | None) -> bool:
    """True if Plane can still hand back the issue we were just told it created."""
    if not issue_id:
        return False
    try:
        resp = requests.get(f"{_base_url()}/issues/{issue_id}/", headers=_headers(), timeout=15)
        return resp.status_code == 200 and resp.json().get('id') == issue_id
    except requests.RequestException:
        return False
