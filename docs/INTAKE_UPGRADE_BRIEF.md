# Article Intake Tab Upgrade — Brief for Claude Design

Single self-contained reference for a Claude Design session redesigning the **Article
Intake** tab specifically (not the whole dashboard — that was a separate, already-shipped
reskin). **This document intentionally contains no aesthetic or visual direction** — no
colors, fonts, or style guidance. All graphic and aesthetic decisions are Claude Design's
to make. Everything below is functional/product context only: what the tab does today,
what's being added, and the real data shapes involved.

Built in **NiceGUI** (Python; renders to Vue/Quasar under the hood) — whatever comes out
of this design session gets translated into NiceGUI components afterward. Prefer standard
layout patterns (flex columns/rows, cards, tables, chips, modals) over bespoke CSS/JS-heavy
interactions. Data refresh is polling (a timer), not a live push/websocket stream.

## 1. What exists today (baseline)

Three-pane layout: folder rail (left) → article list (middle) → reader pane (right).

- **Folder rail**: All / Homelab / News / Errors & Rejections, each with a live count.
  These are auto-categories derived from the article's `primary_domain` field in the
  processing pipeline — not user-editable today.
- **Tag rail**: chips for only the top 12 most-frequent tags across the currently-filtered
  articles; clicking toggles a single-tag filter (on/off, one tag at a time).
- **Free-text search**: matches title, snippet, tags, and full raw content.
- **Queue panel** (above the article list): failed items shown first (red-tinted,
  click-to-retry), active items (pending/processing) shown with a progress/retry-count
  indicator.
- **Article list rows**: badge (Duplicate / Automated / Manual), a priority flag (`P{score}`)
  when `priority_score >= 7.5`, date, source domain, title, snippet, up to 3 tags.
- **Reader pane**: badge + content type + primary domain + date header, an amber
  "Why it matters · Priority {score}" callout box, a Content/AI-Summary tab toggle, and
  three actions — **Delete** (behind a confirm dialog), **Toggle Duplicate**, **Resubmit**
  (re-queues the article by its original source URL).
- Empty states exist for "no articles match search" and "select an article to read."

## 2. What's being added

### 2a. Full searchable tag list + multi-tag filter
Today only 12 tags are ever visible. Replace with a complete, searchable list of every
tag present in the archive (with per-tag counts), scrollable if long. Selecting multiple
tags filters to articles matching **all** selected tags (AND logic — not OR).

### 2b. Custom folders / collections
User-created folders, independent of the existing auto-categories (Homelab/News/Errors
stay as-is). A user assigns an article to one or more custom folders manually. This is
new persisted data, written into the article's own file (see §4) — so folder assignment
survives even if the dashboard app itself is rebuilt or replaced.

### 2c. Read / Unread, Favorite, and Delete — per-row and bulk
Each article gets two new lightweight, independent toggle states, plus quick access to
delete:
  - **Read/Unread** — a on/off toggle, flippable directly from the list row without
    opening the reader.
  - **Favorite** — a separate on/off toggle, also flippable directly from the row.
  - **Delete** — already exists inside the reader pane; add the same action as a quick
    icon/button directly on the list row too (still behind the existing confirm dialog).
  - These per-row quick actions sit alongside (not replacing) a **bulk-selection mode**:
    checkboxes appear per row, and when one or more are selected, a bulk action bar
    appears offering: mark read, mark unread, favorite, move to folder, delete.

### 2d. Compact/table view + sort controls
An alternate, denser list layout — a sortable table/grid (columns: title, date, priority,
tags, read/favorite indicators) — as a toggle alongside the current card-style rows.
Sort options: date, priority score, title (alphabetical), **unread-first**, and
**favorites-first**.

### 2e. Keyboard shortcuts
Global hotkeys for triage without touching the mouse: navigate up/down the list, toggle
bulk-select on the currently-focused row, toggle read/unread, and trigger "send to
HomeLab" (§2g) on the focused article. Should not fire while a text input/search box has
focus.

### 2f. Reading-time estimate
A simple word-count-based estimate (article word count ÷ 250 ≈ minutes), shown per
article in both the list row and the reader pane header.

### 2g. "Send to HomeLab" button
A single-click action, available from both the list row and the reader pane, that:
  1. Creates a new to-do item in an existing external project-tracking system (Plane),
     built from the article's title, a link back to the article, and its AI-generated
     summary/why-it-matters text as the description.
  2. Automatically marks the article as read + archived locally once the to-do is
     created successfully.
  3. Shows a success/failure toast; on failure the article's state is left unchanged.

No project picker — always goes to one fixed, pre-configured destination. This is a
single deliberate action, not a form — no intermediate screen/dialog needed unless the
create call fails (then show the error).

## 3. Cross-cutting notes

- All of the above (favorite/read/folder/archived state) is per-article state layered on
  top of the existing read-only article data — it does not change how articles are
  fetched or processed upstream.
- "Archived" (from 2g) is a distinct state from "Deleted" — archived articles are simply
  hidden from the default list view (they still exist and are recoverable), where deleted
  articles are gone. Design should account for some way to view/restore archived articles
  (a filter/toggle, not necessarily a whole separate page).
- Single user, desktop-first, browser tab left open — same as the rest of the dashboard.

## 4. Real data shapes

### Article (existing fields, read-only, unchanged)
```python
article = {
    'id': str,                  # filename, e.g. "2026-07-22-193726-some-title.md"
    'title': str,
    'date': str,                 # "YYYY-MM-DD HH:MM"
    'source': str,                # source URL
    'snippet': str,               # short excerpt, ~150 chars
    'is_duplicate': bool,
    'auto_generated': bool,       # True = "Automated" badge, False = "Manual" badge
    'category': str,               # "Homelab" | "News" (auto, from primary_domain)
    'tags': list[str],
    'content_type': str,           # e.g. "Guide", "Reference", "Tutorial"
    'primary_domain': str,         # e.g. "reddit.com", "homelab"
    'priority_score': float | None,   # 0-10ish, e.g. 8.6
    'why_it_matters': str | None,
    'status': str,
}
# Full content + AI summary fetched separately per-article on open:
article_content = {'content': str, 'summary': str}
```

### New: per-article workflow state (new sidecar file, dashboard-owned)
```python
workflow_state = {
    "<article_id>": {
        "read": bool,        # default False
        "favorite": bool,    # default False
        "archived": bool,    # default False
    },
    ...
}
```

### New: custom folder assignment (written into the article's own file, not the sidecar)
```python
# New optional field alongside the article's existing frontmatter fields:
"user_folders": list[str]   # e.g. ["Project X reference", "Weekend reading"]
```

### New: "Send to HomeLab" payload (outbound, to the existing Plane project)
```python
plane_issue = {
    "name": str,          # article title
    "description": str,    # why_it_matters/summary + link back to the article
    "labels": ["from-article"],
}
```
