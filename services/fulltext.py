"""On-demand full-article-text fetch for the reader's 'Full article' section.

The intake daemon extracts each page's full text at ingest (trafilatura) but only
feeds it to the summarizer -- nothing stores it. Rather than change the daemon and
backfill 100+ articles, the dashboard fetches the source URL the first time an
article's reader asks for it and caches the result on disk, so every article --
past or future -- gets full text on first open and instant loads after that.

Cache: one markdown file per article id under fulltext_cache/ (gitignored).
Only successes are cached; failures (paywall, dead link, network) return None so
the UI can offer a retry -- a transient failure must not poison the cache.

All functions are synchronous (called via run.io_bound, matching services/intake.py).
"""
import contextlib
import os
import tempfile

import trafilatura

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fulltext_cache')


def _cache_path(article_id: str) -> str:
    # article ids are bare filenames ('2026-...-title.md'); never treat as paths
    return os.path.join(CACHE_DIR, os.path.basename(article_id))


def get_cached(article_id: str) -> str | None:
    try:
        with open(_cache_path(article_id), 'r', encoding='utf-8') as f:
            return f.read()
    except OSError:
        return None


def fetch_and_cache(article_id: str, url: str) -> str | None:
    """Fetch the source page, extract readable text, cache and return it.
    Returns None on any failure (caller shows a fallback + retry)."""
    if not url:
        return None
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded, output_format='markdown',
                                    include_images=False, include_tables=True)
        if not text:
            text = trafilatura.extract(downloaded)
    except Exception:
        return None
    if not text or not text.strip():
        return None
    text = text.strip()
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, _cache_path(article_id))
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return text  # extraction worked; a cache-write failure shouldn't hide it
    return text
