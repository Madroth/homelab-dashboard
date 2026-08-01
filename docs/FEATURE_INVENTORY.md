# Feature Inventory — OmegaLab Dashboard

Every interactive behavior currently implemented, page by page. This is the parity
checklist for a reskin: after wiring new visuals from Claude Design, walk this list and
confirm each item still works — a redesign should carry all of it forward unless a
change is deliberate, not a silent drop.

Companion docs: `DESIGN_BRIEF.md` (what Claude Design needs), `IMPLEMENTATION_GUIDE.md`
(architecture patterns + service contracts for wiring the new visuals to existing logic).

## Global shell (`components/layout.py`, `nav_sidebar.py`)

- [ ] Left nav: 6 tabs (Dashboard / Article Intake / Mod Pipeline / Media Curator /
      Settings / System Status), active tab highlighted
- [ ] Tab state persists in the URL (`?tab=intake`) and survives a page reload
- [ ] Two disabled/reserved nav items shown but not clickable: Containers, Network
      (placeholders for future pages)
- [ ] Quick-links block (Crafty Controller, Plane, Freqtrade) — opens in a new tab
- [ ] "System Operational" pulse indicator at the bottom of the nav
- [ ] Top bar: AI toggle button (wand icon) opens/closes the chat sidebar; user-avatar
      placeholder circle ("P")

## AI Assistant sidebar (`components/chat_sidebar.py`, `services/ai/*`)

- [ ] Collapsible right-hand panel, slides in/out (not a separate page/route)
- [ ] Model picker: Claude / Agy / Local — switching models mid-conversation is allowed
- [ ] Chat history renders in-panel (user bubbles right-aligned/accent, model bubbles
      left-aligned with markdown rendering, error bubbles in red) — history is
      **client-side only**, lost on refresh (not currently persisted)
- [ ] Spinner shown while waiting for a reply; textarea + send button (click or Enter)
- [ ] The assistant automatically knows what's on the active tab (open article, pending
      mod count, media queue, container health, etc.) with no user action required
- [ ] The assistant can call real tools: search the article archive, list/approve/reject
      mods and media items, check Minecraft status — all three models share the same
      tool set
- [ ] No token streaming — full reply appears at once after the spinner (intentional,
      not a bug, per prior scoping conversation)

## Home / Dashboard (`pages/home.py`)

- [ ] Minecraft server status card: online → player count + version; offline → error
      message
- [ ] Auto-refreshes every 10s, plus once immediately on page load
- [ ] **Thinnest page today** — meant to become a cross-page "what needs my attention"
      overview; current version only shows one card

## Article Intake (`pages/intake.py`, `services/intake.py`, `services/intake_state.py`)

Current as of the 2026-07-31 bug-fix pass — see `INTAKE_UPGRADE_BRIEF.md` for the full
functional brief (data shapes, cross-cutting notes, and §6's list of what still needs a
real Design pass). Summary checklist:

- [ ] Collapsible rail: categories (All/Homelab/News/Errors & Rejections, live counts,
      always excluding archived), user-created "My Folders" + a fixed Archived entry,
      and a full searchable tag list (own filter box, per-tag counts, multi-select AND
      filter)
- [ ] Toolbar: free-text search (title/snippet/tags/full text), sort dropdown (date,
      priority, title, unread-first, favorites-first), cards/table view toggle, Select
      (bulk mode) button, keyboard-shortcut cheat-sheet modal
- [ ] Summary line ("N articles · N unread" + active tag-filter count) and an "Include
      archived" checkbox
- [ ] Queue panel above the article list:
  - [ ] Failed items shown first, visually distinguished, click-to-retry
  - [ ] Active items (pending/processing) shown with a retry-count indicator when
        applicable
- [ ] Article list, both cards and table view: type badge (Duplicate/Automated/Manual),
      priority flag, favorite indicator, Discuss message-count chip, date, reading-time
      estimate, source domain, tags, read/unread visual distinction; cards view also
      shows a snippet and up to 2 custom-folder labels
- [ ] Table view sort headers reach all 5 sort modes (3 labeled + 2 icon-only)
- [ ] Per-row actions (both views): toggle read/unread, toggle favorite, toggle
      archived/unarchived, send to HomeLab (shows an in-flight state during the network
      call), delete (confirm-gated)
- [ ] Bulk-selection mode: per-row checkboxes, bulk action bar (mark read/unread,
      favorite, archive, unarchive, move to folder, delete); selection clears on folder
      switch
- [ ] Keyboard shortcuts: j/k or arrows to move a highlighted-row cursor, Enter to open,
      x to select, r/f/a to toggle read/favorite/archived, s to send, Del to delete, Esc
      to clear cursor, ? for the cheat sheet
- [ ] Empty states: no-tag-match, no-search-match, no-articles, and a loading state
      before the first fetch completes
- [ ] Reader pane, **Read mode**: badge/content-type/domain/date/reading-time header, a
      "Why it matters · Priority" callout when present, Content/AI-Summary tab toggle,
      Delete (confirm-gated) / Toggle Duplicate / Resubmit / Send to HomeLab actions
- [ ] Reader pane, **Discuss mode** (built after the last Design pass — see
      `INTAKE_UPGRADE_BRIEF.md` §6): 3-way model picker (Claude/Agy/Local), 3 toggleable
      grounding-source chips (this article / homelab repo / article archive), suggested
      starter prompts, message thread with tool-call indicators and expandable
      repo/article citations, clear-thread action
- [ ] Empty reader state: "Select an article to read"

## Mod Pipeline (`pages/mods.py`, `services/mods.py`)

- [ ] Pending-review grid: mod name + version badge, "by \<submitter\> · \<date\>",
      truncated sha256 hash (monospace)
- [ ] "Read Review" button → modal showing the full AI-generated review (markdown)
- [ ] Approve button → deploys the mod (moves through staging → approved → deployed,
      updates the registry)
- [ ] Reject button → prompts for a rejection reason (textarea), moves to review folder
- [ ] Pipeline-history grid: previously deployed mods, version badge, submitter/date,
      "Approved \<date\> · deployed by \<decided_by\>"
- [ ] Empty states for both grids
- [ ] Manual reload after every approve/reject

## Media Curator (`pages/media.py`, `services/media.py`)

- [ ] Quick-links row: 9 external service icons (Radarr, Sonarr, Prowlarr, Bazarr,
      Tautulli, Pulsarr, Uptime-Kuma, qBittorrent, Plex) — opens in a new tab
- [ ] Queue list, two visual states per row:
  - [ ] **Approved** items: compact row, click opens the details modal
  - [ ] **Pending** items: fuller card with year, "NEEDS REVIEW" badge when flagged,
        inline Approve / Edit Title / Reject buttons
- [ ] Details modal (approved items): category reclassify dropdown (moves the file and
      re-runs identification on change), original filename vs. target path, franchise,
      short description, long description, sort logic/reasoning, Reject/Delete, Close
- [ ] Edit Title modal (pending items): text input, Cancel/Save
- [ ] Reject/Delete requires confirm dialog
- [ ] Empty state: "Queue is empty. Waiting for media..."
- [ ] Auto-refreshes every 5s, plus once on load
- [ ] **Not yet built** (see `DESIGN_BRIEF.md` §8 for the full original feature brief on
      this page specifically): cover art/thumbnails, advanced search/filters, bulk
      actions, undo/rollback, in-browser preview player, drag-and-drop upload,
      duplicate-resolution center, disk-space widget, custom tagging, live audit log

## System Status (`pages/system.py`, `services/system.py`)

- [ ] DEFCON alert banner — red, only rendered when at least one alert string is present
      (e.g. storage critical, VPN down, daemon crashed)
- [ ] Container health grid — one card per Docker container, color-coded (green/amber/red
      by status text)
- [ ] Three metric cards: disk free/total for `/mnt/Multimedia`, Plex memory usage
      (with a hard-limit label), daemon active/inactive status
- [ ] Daemon log tail — last 100 lines, rendered as a code block, manual refresh button
- [ ] Auto-refresh: container/metric data every 15s + once on load; log tail loads once on
      load (manual refresh only, no polling)

## Settings (`pages/settings.py`, `services/settings.py`)

- [ ] Four fields: Gemini API key (masked, toggleable), Anthropic API key (masked,
      toggleable), Ollama Host, Ollama Model
- [ ] Save button persists all four; existing masked values are preserved (re-saving
      doesn't overwrite a key with a masked placeholder — see `services/settings.py`)
- [ ] Loads existing saved values on page open
- [ ] Purely a form today — no visual grouping/help text beyond the section header

## Explicitly out of scope / dead code

- [ ] `app.py` (Flask, ~1000 lines) and `static/` (`app.js`, `index.html`, `style.css`) —
      the pre-NiceGUI version of this dashboard. **Not running, not imported by anything
      in the live app.** Don't try to reconcile or migrate anything from it; the NiceGUI
      stack (`main.py` → `components/` → `pages/` → `services/`) is the only live
      implementation.
