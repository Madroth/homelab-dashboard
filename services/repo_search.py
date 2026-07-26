"""Pure-Python line search over ~/HomeLab for the AI Discuss feature's repo grounding.
No ripgrep dependency (not installed on this host) and no embeddings index -- the repo
is small (dozens of text files, single-digit MB), so a synchronous full scan per query
is fast enough and needs no staleness/index management. A disclosed simplification
versus the original brief's "embeddings or ripgrep-backed" suggestion.
"""
import os
import re

REPO_ROOT = os.path.expanduser('~/HomeLab')
SKIP_DIRS = {'.git', 'venv', '__pycache__', 'node_modules', '.cache'}


def _iter_text_files():
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)


def grep_repo(query: str, top_k: int = 8) -> list[dict]:
    """Returns [{'path': relative-to-repo-root, 'line': 1-indexed, 'snippet': str}],
    scored by how many distinct query terms each line contains, highest first."""
    terms = [t for t in re.findall(r'\w+', query.lower()) if len(t) > 2]
    if not terms:
        return []

    matches = []
    for filepath in _iter_text_files():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue

        for i, line in enumerate(lines):
            lower = line.lower()
            score = sum(1 for t in terms if t in lower)
            if score:
                matches.append((score, filepath, i + 1, line.strip()))

    matches.sort(key=lambda m: -m[0])
    results = []
    for score, filepath, lineno, snippet in matches[:top_k]:
        results.append({
            'path': os.path.relpath(filepath, REPO_ROOT),
            'line': lineno,
            'snippet': snippet[:200],
        })
    return results


def repo_file_count() -> int:
    return sum(1 for _ in _iter_text_files())
