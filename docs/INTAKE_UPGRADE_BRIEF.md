# Article Intake Tab — Brief for Claude Design

Single self-contained reference for a Claude Design session doing a **visual** pass on
the Article Intake tab (not the whole dashboard — that was a separate, already-shipped
reskin, see `DESIGN_BRIEF.md`). **This document intentionally contains no aesthetic or
visual direction** — no colors, fonts, or style guidance beyond describing functional
relationships that already exist (e.g. "failed items are visually distinguished from
active ones"). All graphic and aesthetic decisions are Claude Design's to make.
Everything below is what the tab actually does today and the real data behind it.

Built in **NiceGUI** (Python; renders to Vue/Quasar under the hood) — whatever comes out
of this design session gets translated into NiceGUI components afterward. Prefer
standard layout patterns (flex columns/rows, cards, tables, chips, modals) over bespoke
CSS/JS-heavy interactions. Data refresh is on-demand (an action triggers a targeted
re-render), not a live push/websocket stream.

> **Status**: everything in §1–§5 below is built and live, not a proposal — a prior
> Design pass (2026-07-25) shipped the layout, and a subsequent bug-fix pass
> (2026-07-31) corrected several behaviors without changing the visual design at all.
> **§6 flags exactly which pieces have never been through a real Design pass** — that's
> the highest-value place to focus new visual work.

---

## 1. Overall layout

Three-pane: **rail** (left, collapsible) → **article list + toolbar** (middle, fixed
width) → **reader** (right, fills remaining space).

- Rail collapses to a slim icon-only strip (just the 4 category icons, click to expand
  back) via a toggle at its top edge.
- The middle pane header is a toolbar: search box, sort dropdown, cards/table view
  toggle, a "Select" button (enters bulk-selection mode), and a "?" button (keyboard
  shortcut cheat sheet, a modal).
- Below the toolbar: a one-line summary ("N articles · N unread", plus a tag-filter
  count when active) and an "Include archived" checkbox.
- Below that: a queue panel (only rendered when there are active/failed queue items),
  then the article list itself (cards or table, per the view toggle).
- The reader pane has its own two-mode header tab: **Read** / **Discuss** (§4).

## 2. Rail: categories, custom folders, tags

- **Categories** (auto, not user-editable): All / Homelab / News / Errors & Rejections,
  each with a live count. Errors & Rejections combines duplicate-flagged articles and
  permanently-failed queue items.
- **My Folders**: user-created, arbitrary names, plus a fixed **Archived** entry at the
  bottom (its own live count). A "+" button opens a small dialog to create a new folder
  (just a name field). Folder counts and category counts always exclude archived
  articles, regardless of whether "Include archived" is checked in the toolbar below —
  they're meant to read as "how much is actually in front of me," not a raw total that
  jumps by thousands the moment a display filter changes.
- **Tags**: every tag present in the currently-scoped articles, sorted by frequency,
  each showing a count, with its own filter-the-tag-list search box. Clicking a tag
  toggles it into a multi-select filter set — selecting multiple tags requires an
  article to match **all** of them (AND, not OR). A "clear N" link appears when any are
  selected.

## 3. Article list: cards view and table view

Both views show the same underlying data, laid out differently. **Sorting** applies to
both: newest-first (real chronological order), priority (descending), title (A–Z),
unread-first, favorites-first — all 5 are reachable from either view (cards via a
dropdown in the toolbar; table view also has two icon-only sortable column headers,
alongside labeled TITLE/DATE/PRIORITY headers, for the unread/favorite modes).

**Per-row indicators** (both views): a type badge (Duplicate / Automated / Manual), a
priority flag when the article's priority score is high, a favorite-star indicator, a
small message-count indicator when the article has an active Discuss thread (§4), date,
estimated reading time (word count ÷ 250), source domain, up to 2–3 tags, and — cards
view only — up to 2 custom folder labels and a one-line snippet. Unread articles are
visually distinguished from read ones (weight/color difference on the title, plus a
small accent mark in cards view).

**Per-row actions** (both views): toggle read/unread, toggle favorite, toggle
archived/unarchived, send to HomeLab, delete — five independent icon-buttons, each
tracking its own true/false state where applicable (read, favorite, archived are all
independently flippable; send and delete are one-shot actions, not toggles). All five
should stay visually distinguishable from each other at a glance, since they sit
adjacent in a tight icon row/cell.

**Bulk selection**: the "Select" toolbar button reveals a checkbox on every row;
selecting one or more reveals a bulk-action bar (mark read, mark unread, favorite,
archive, unarchive, move to folder, delete). Selection automatically clears when
switching folders or exiting select mode.

**Send to HomeLab** needs a visible **in-flight state** — clicking it kicks off a real
network call (creating a to-do in an external tracker) that can take a moment; the row
must show something is happening (today: a spinner replacing the icon) rather than
looking unresponsive, and resolve to either a success state (the article becomes
read+archived) or a failure notification.

**Empty states**: "No articles match all N selected tags," "No articles match
'\<search\>'," and a generic "No articles found" — plus a loading state (spinner +
"Loading articles…") shown before the first fetch completes.

## 4. Reader pane: Read mode and Discuss mode

A two-tab header switches the reader between:

**Read mode**: badge + content-type + primary-domain + date + reading-time header line,
an accent-colored "Why it matters · Priority {score}" callout box (when present),
a Content/AI-Summary tab toggle, the rendered markdown body, and a row of actions:
Delete (confirm-gated), Toggle Duplicate, Resubmit (re-queues by original source URL),
Send to HomeLab (same in-flight-state requirement as the row-level button, §3).

**Discuss mode**: a grounded chat interface scoped to the open article. Elements:
- A 3-way model picker (Claude / Agy / Local) — switching mid-conversation is allowed.
- Three toggleable "grounding source" chips: *This article* (word count shown),
  *homelab repo* (live file count), *Article archive* (saved-article count) — each can
  be independently included/excluded from what the assistant is allowed to search.
- When the thread is empty: 2 suggested starter prompts (content-type-aware — a
  guide/tutorial/reference article gets different suggestions than a general one) as
  clickable chips, plus a placeholder message.
- Message thread: user bubbles right-aligned, assistant bubbles left-aligned rendering
  markdown, a "thinking" spinner state while waiting on a reply.
- Tool-call indicators inline in assistant messages (a small pill: tool name + a short
  detail string + a checkmark) when the assistant used a grounding source.
- Citations render as small expandable strips under a message: a **repo** citation
  shows `path:line` and expands to a code snippet; an **article** citation shows the
  article title and, when clicked, opens that article in Read mode (switching the
  reader's content, not navigating away).
- A grounding-footer line (small, describes what's currently in scope) and a "Clear
  thread" link when the thread isn't empty.
- Message input is a single-line box + send button/Enter key.

Message count persists per-article (shown as the list-row chip described in §3) and the
whole thread persists across reader sessions until explicitly cleared.

## 5. Keyboard shortcuts

Global hotkeys (disabled while a text input/select/button has focus), with a "?"
cheat-sheet modal: `j`/`↓` and `k`/`↑` move a highlighted-row cursor, `Enter` opens the
focused row, `x` toggles its selection (entering select mode if needed), `r` toggles
read/unread, `f` toggles favorite, `a` toggles archived, `s` sends to HomeLab, `Del`/
`Backspace` deletes (confirm-gated), `Esc` clears the highlighted-row cursor.

---

## 6. What's never been through a Design pass — highest-value focus areas

Everything above is functionally complete and correct, but some of it only ever got
whatever ad-hoc inline styling a Claude Code session gave it, never a real visual
design pass:

- **The entire Discuss mode (§4)** — built after the last Design session shipped. Model
  picker, source chips, message bubbles, citation strips, and the input row are all
  first-draft visual treatment.
- **The archive/unarchive icon and its bulk-bar buttons** — added in the most recent
  bug-fix pass; visually it's just a copy of the existing read/favorite icon pattern,
  never independently considered.
- **The in-flight "sending" state on Send to HomeLab** (§3) — currently just a spinner
  swapped in for the icon; worth a more considered treatment given it's the one action
  in this tab with a real, sometimes-slow network round-trip.
- **The Discuss message-count chip on list rows** (§3) — brand new, minimal treatment
  (a small icon + number).
- **The two icon-only sort headers in table view** (§3) — added to close a functional
  gap (table view couldn't reach 2 of 5 sort modes); currently bare icons with a hover
  tooltip, no distinct visual treatment from the labeled text headers next to them.

Everything else (rail, toolbar, card/table list body, Read-mode reader) already went
through the 2026-07-25 Design pass and should be treated as "refine," not "design from
scratch."

---

## 7. Cross-cutting notes

- Single user, desktop-first, browser tab left open — same as the rest of the
  dashboard.
- "Archived" is distinct from "Deleted": archived articles are hidden from the default
  list view but still exist and are fully recoverable (toggle it back, or use the
  Archived folder + "Include archived" to find them). Deleted articles are gone.
- No project picker for Send to HomeLab — always goes to one fixed, pre-configured
  destination. It's a single deliberate action, not a form.
- Data refresh is action-triggered (a click/keypress causes a targeted re-render), not
  a polling timer or live stream, for everything in this tab.

---

## 8. Real data shapes

### Article (read-only, from `homelab-intake`)
```python
article = {
    'id': str,                    # filename, e.g. "2026-07-30-235959-Some-Title.md"
    'title': str,
    'date': str,                   # "YYYY-MM-DD HH:MM:SS" (frontmatter) or free text (legacy)
    'source': str,                  # source URL
    'snippet': str,                 # short excerpt, ~150 chars, boilerplate stripped
    'is_duplicate': bool,
    'auto_generated': bool,         # True = "Automated" badge, False = "Manual" badge
    'category': 'Homelab' | 'News', # auto, from primary_domain
    'tags': list[str],
    'content_type': str,             # e.g. "Guide", "Reference", "Tutorial"
    'primary_domain': str,           # e.g. "reddit.com", "homelab"
    'priority_score': float | None,  # 0–10ish
    'why_it_matters': str | None,
    'status': str,
    'user_folders': list[str],       # custom folder names this article is filed under
    'reading_minutes': int,          # word count ÷ 250, minimum 1
}
# Full content + AI summary, fetched per-article on open:
article_content = {'content': str, 'summary': str}
```

### Per-article workflow state (dashboard-owned sidecar, `intake_state.json`)
```python
workflow_state = {
    "<article_id>": {"read": bool, "favorite": bool, "archived": bool},
    ...
}
prefs = {"view": "cards" | "table", "sort": "date" | "priority" | "title" | "unread" | "favorite"}
folders = ["Project X reference", "Weekend reading", ...]   # user-created folder names
```

### Discuss thread + citations (dashboard-owned, `intake_conversations.json`)
```python
message = {
    "role": "user" | "assistant",
    "text": str,
    "tools": [{"name": str, "detail": str}],       # assistant messages only
    "cites": [
        {"kind": "repo", "path": str, "line_start": int, "snippet": str} |
        {"kind": "archive", "article_id": str, "title": str}
    ],
}
thread_counts = {"<article_id>": int}   # message count per article, for the list chip
```

### "Send to HomeLab" payload (outbound, to an existing Plane project)
```python
plane_issue = {
    "name": str,             # article title
    "description_html": str,  # summary/why_it_matters + a link back to the source
    "labels": ["from-article"],
}
```
