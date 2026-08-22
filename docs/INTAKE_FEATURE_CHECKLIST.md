# Article Intake — Complete Feature & Test Checklist

Code-verified inventory of every behavior, link, and visual on the Article Intake page
(plus the global nav it lives in), derived directly from `pages/intake.py`,
`components/discuss_panel.py`, and `components/nav_sidebar.py` as of commit `e0ea2ff`.

**How to use:** check items off as they pass in a real browser. Log failures with what
you did / expected / got. The companion `INTAKE_V2_TESTING_GUIDE.md` is the
scenario-driven walkthrough; this doc is the exhaustive parity list — everything the
code implements should appear here exactly once.

**Legend:** every item is tagged **[B]** behavior · **[L]** link/navigation ·
**[V]** visual/graphic.

**Already verified headlessly** (48 tests in `test_intake_fixes.py`): date sorting +
legacy-filename fallback, queue-file lock, archiving folder-scoping rules, single-row
refresh pattern, delete cleanup, Discuss thread persistence. Headless ≠ looked-at:
those items still appear below for a visual pass, marked ⚙ where the logic itself is
already covered.

---

## 1. Global nav rail (`nav_sidebar.py`)

### Expanded state
- [ ] [V] OmegaLab logo block (server icon in tinted square) + wordmark at top
- [ ] [V] Three group headers: WORKSPACE, INFRASTRUCTURE, SERVICES (small caps, dim)
- [ ] [V] WORKSPACE items: Dashboard, Article Intake, Mod Pipeline, Media Curator
- [ ] [V] INFRASTRUCTURE items: System Status, Containers, Network, Settings
- [ ] [V] SERVICES items: Crafty Controller (gamepad icon), Plane, Freqtrade — each with
      a small external-link arrow glyph
- [ ] [V] Crafty's gamepad icon reads as distinct from Mod Pipeline's cubes icon at a glance
- [ ] [B] Active tab is highlighted; clicking another workspace/infra item switches tabs
- [ ] [B] Containers and Network are disabled: greyed out, `not-allowed` cursor, no click
- [ ] [V] Article Intake unread-count badge (amber pill) shows the true unread,
      non-archived, non-duplicate count
- [ ] [B] ⚙ Badge updates live when you mark an article read/unread/archived on the
      intake page — no tab switch or reload needed (`live_state.refresh_all`)
- [ ] [V] Mod Pipeline pending-count badge still renders and is correct
- [ ] [V] "System Operational" footer: green dot with a 2s pulse animation
- [ ] [B] Tab state survives reload via `?tab=` in the URL

### Collapse / expand
- [ ] [B] Collapse arrow (top) shrinks the rail to a 48px icon-only strip
- [ ] [B] In collapsed state, hovering each icon shows a tooltip naming it
- [ ] [V] Collapsed badges render as tiny amber count dots pinned to the icon corner
- [ ] [B] Expand arrow restores the full rail, same groups, active tab still highlighted

### External links (SERVICES group — open in a NEW tab)
- [ ] [L] Crafty Controller → `https://100.87.245.107:8443` (expect a cert warning — self-signed)
- [ ] [L] Plane → `http://100.87.245.107`
- [ ] [L] Freqtrade → `http://100.87.245.107:8082` (may be down — quant lab is
      hibernated; "connection refused" is expected, a wrong-URL redirect is not)
- [ ] [L] All three also work from the collapsed icon-only rail

---

## 2. Page header

- [ ] [V] "Article Intake" title, left-aligned, bold
- [ ] [V] Four icon-only buttons right-aligned, each with a tooltip:
      add_link, play_arrow, menu_book, question_mark
- [ ] [B] **Add URL** button → info toast "not wired to a backend yet" (stub — expected)
- [ ] [B] **Run intake** button → info toast "not wired to a backend yet" (stub — expected)
- [ ] [B] **Library** button → info toast "coming in a later phase" (stub — expected)
- [ ] [B] **?** button → opens the keyboard-shortcut cheat sheet
- [ ] [B] Stats line "N articles · N unread · N archived · queue N" — spot-check all four
      numbers against reality; "article" singularizes when N = 1
- [ ] [B] ⚙ Stats line updates immediately after read/archive/delete actions
- [ ] [V] Header wraps to two rows cleanly when the list column is narrow (reader open)

---

## 3. Toolbar — search, folders, sort, density, select

### Search
- [ ] [B] Free-text search matches title, snippet, tags, AND full text (try a word that
      only appears in an article's body)
- [ ] [B] List and stats narrow as you type (search fires on change, not on Enter)
- [ ] [V] Magnifier icon + placeholder "Search title, snippet, tags, full text…"
- [ ] [B] Clearing via the chip's × empties the search box itself too (not just the filter)

### Folder/status dropdown
- [ ] [V] Closed state shows folder icon + current selection + chevron
- [ ] [B] Menu lists All / Favorites / Duplicates / Archived, each with an icon and a
      live count
- [ ] [V] Divider, then "MY FOLDERS" section header, then custom folders (purple folder
      icons) with counts — section only appears if custom folders exist
- [ ] [V] Long custom-folder names truncate with an ellipsis instead of breaking the menu
- [ ] [B] Divider, then "+ New folder" → opens a name dialog with Cancel/Create
- [ ] [B] Creating a folder adds it to the menu immediately; empty name is a no-op
- [ ] [B] Selecting any entry closes the menu, filters the list, updates the highlight
- [ ] [B] Switching folders clears tag filters, clears any selection, and exits select mode

### Tag dropdown — **⏸ ON HOLD** (tag work parked per Chris 2026-08-02; skip this block,
revisit alongside the dedicated tag-filter UI feature)
- [ ] [B] Menu stays open across multiple tag clicks (persistent-menu workaround)
- [ ] [B] Tag search box narrows the tag list; "No tags match." empty state
- [ ] [V] Selected tags: check mark + accent color + tinted row; button shows "Tags (N)"
- [ ] [B] "clear N" link resets all tags; per-tag counts reflect the current folder scope
- [ ] [B] Multi-tag filter is AND (article must carry every selected tag)
- [ ] [V] Tag list scrolls past ~260px; sorted by count descending

### Sort dropdown
- [ ] [B] All 5 modes visibly change the order: Unread first / Newest first / Priority /
      Title A-Z / Favorites first
- [ ] [B] ⚙ "Newest first" is correct even for legacy articles with free-text dates
      (falls back to the filename timestamp)
- [ ] [B] Sort choice persists across a page reload (saved to prefs)

### Density toggle
- [ ] [V] Two-icon segmented control; active side tinted; tooltips explain Cozy vs Compact
- [ ] [B] Compact: tighter rows, no type badge, no source line, no snippet, no tag chips
- [ ] [B] Cozy: badge + source + snippet + up to 3 tags + up to 2 purple folder labels return
- [ ] [B] Density choice persists across a page reload

### Select button
- [ ] [B] Toggles select mode on/off; button fills with accent color while active
- [ ] [B] Turning select mode off clears any checked rows

### Filter chips row
- [ ] [V] One removable chip per active filter: folder (icon chip), each tag, search
      term (quoted); row hidden entirely when no filters are active
- [ ] [B] Each chip's × removes exactly that filter
- [ ] [B] "Clear all" resets folder to All, clears tags and search in one click

---

## 4. Folder semantics (the archiving model — decided 2026-07-31)

- [ ] [B] ⚙ **All** hides archived AND duplicate articles (main triage view)
- [ ] [B] ⚙ **Favorites** shows favorited articles *including archived ones*
      (favorite → archive → still visible here; the scenario that drove the design)
- [ ] [B] ⚙ **Duplicates** shows duplicate-flagged articles *including archived ones*
- [ ] [B] ⚙ **Custom folders** show their articles *including archived ones*
- [ ] [B] ⚙ **Archived** shows exactly the archived set; un-archiving from here removes
      the row and returns it to All
- [ ] [B] There is NO "Include archived" checkbox anywhere (removed in v2 — its
      reappearance would be a regression)

---

## 5. Queue panel (above the article list)

- [ ] [V] Failed items: red-tinted cards under a "FAILED · CLICK TO RETRY" header,
      showing domain + last error (error truncates with ellipsis)
- [ ] [B] Clicking a failed item retries it; "Retry all" retries every failed item
- [ ] [V] Active items: amber cards with a status dot, domain, and status label
- [ ] [V] A pending item with retries shows "RETRY n/3" instead of "PENDING"
- [ ] [B] Queue count in the header stats line matches pending+processing+failed
- [ ] [B] Panel is empty/absent when the queue is clear (no leftover frame)

---

## 6. Article list

### Loading & empty states
- [ ] [V] First load: 6 shimmering skeleton rows before articles appear
- [ ] [V] No search match: `No articles match "term"` + "Clear filters" link
- [ ] [V] No tag match: "No articles carry all N selected tags." + link (⏸ tag-related)
- [ ] [V] Empty folder: "No articles found."; the Clear-filters link only appears when
      a filter is actually active
- [ ] [B] "Clear filters" link resets everything (same as chip row's Clear all)

### Row visuals (cozy)
- [ ] [V] Type badge: "Duplicate" (orange) / "Automated" (accent) / "Manual" (grey)
- [ ] [V] Priority flag: bolt icon + "P{score}" in amber, only when score ≥ 7.5
- [ ] [V] Favorite star (amber) when favorited
- [ ] [V] "ARCHIVED" pill on archived rows (visible in Favorites/Duplicates/custom/Archived views)
- [ ] [V] Discuss chip: comment icon + message count, only when a thread exists
- [ ] [V] Right-aligned meta: "N min" reading estimate + date
- [ ] [V] Unread: bold title, brighter color, 2px accent left border.
      Read: lighter weight, muted color, no border
- [ ] [V] Source line: link icon + domain only (not the full URL); "Unknown source"
      fallback when the article has no source
- [ ] [V] Snippet line in accent color, single line, ellipsized
- [ ] [V] Up to 3 grey tag chips + up to 2 purple custom-folder chips
- [ ] [V] Focused row (keyboard cursor or open article) gets a tinted background

### Row actions (icon strip under each row's text)
- [ ] [B] Clicking anywhere on the row's text opens the reader; clicking any action icon
      does NOT also open the reader (click.stop guard)
- [ ] [B] Read/unread toggle: circle ↔ green check; title style changes instantly;
      only that row re-renders (no full-list flicker, no scroll jump) — this was one of
      the 2026-08-01 perf bugs, confirm it's actually fast now
- [ ] [B] Favorite toggle: outline ↔ filled amber star, same single-row speed
- [ ] [B] Archive toggle: row leaves the All view immediately (membership changed →
      full-list refresh is expected here)
- [ ] [B] Send to HomeLab: icon swaps to a spinner in the same 28px slot *immediately*;
      resolves to a success toast ("to-do created, article archived" — article becomes
      read+archived) or a red failure toast
- [ ] [L] After a successful send, the to-do actually exists in Plane (check the project)
- [ ] [B] Re-clicking send while a send is in flight is ignored (no double to-do)
- [ ] [V] Once sent, the control is a green checkmark, inert, tooltip "Already sent to
      HomeLab" — the id is persisted as `plane_issue_id`, so it survives a reload
- [ ] [B] The `s` shortcut on an already-sent article toasts "Already sent to HomeLab."
      rather than filing a second to-do (the control is inert, the shortcut still fires)
- [ ] [B] A send that reaches Plane but whose reply is lost does not duplicate: the resend
      comes back "Already filed in HomeLab · linked to the existing to-do" (info toast,
      Plane answers the repeated `external_id` with 409). Hard to stage by hand — covered
      headlessly in `test_intake_fixes.py`
- [ ] [B] A send that fails unexpectedly still resolves the spinner and shows the reason —
      no row left spinning forever
- [ ] [B] Delete: action strip swaps IN PLACE to "Delete? Yes / No" (inline, not a modal)
- [ ] [B] Delete → No restores the normal icon strip
- [ ] [B] Delete → Yes on a throwaway article: row disappears, article file really gone
- [ ] [B] Deleting the article that's open in the reader also closes/blanks the reader;
      deleting a different article leaves the open reader untouched (⚙)

### Row overflow menu (⋯)
- [ ] [L] "Open original" → article's source URL in a new tab (entry hidden when the
      article has no source)
- [ ] [B] "Discuss with AI" → opens the reader directly in Discuss mode
- [ ] [B] "Move to folder" → dialog offering existing folders + type-a-new-name; new
      name creates the folder; article then shows the purple folder chip
- [ ] [B] "Flag as duplicate" / "Clear duplicate flag" — label matches the article's
      current state; toggling updates the badge and Duplicates count
- [ ] [B] "Resubmit" → "Queued for resubmission" toast + item appears in the queue panel
      (or a red failure toast)

---

## 7. Bulk selection

- [ ] [V] Select mode: a checkbox square appears on every row; checked = accent fill +
      check mark
- [ ] [B] Bulk bar appears only once ≥ 1 row is checked; shows "N selected"
- [ ] [B] Mark read / Mark unread apply to all checked rows (toast confirms count)
- [ ] [B] Favorite applies to all checked rows
- [ ] [B] Archive / Unarchive apply to all checked rows
- [ ] [B] Move to folder: one dialog, moves every checked article
- [ ] [B] **Delete shows a confirmation MODAL** (bulk is deliberately modal; single-row
      is deliberately inline — confirm both styles exist)
- [ ] [B] Clear button unchecks everything and hides the bar
- [ ] [B] Switching folders while rows are checked clears the selection automatically

---

## 8. Reader pane — Read mode

### Layout & sizing (the 2026-08-01 rework — test deliberately)
- [ ] [B] Opening an article: list narrows to a fixed 380px, reader fills ALL remaining
      width (no dead blank strip on a wide monitor)
- [ ] [B] **Scroll partway down the list, open a mid-list article — the list does NOT
      jump back to the top.** (The single most important check in this doc.)
- [ ] [B] Opening an article feels instant (was 1s+ before the 2026-08-01 fix)
- [ ] [B] Expand icon → full width, list fully hidden
- [ ] [V] Full-width mode's way back is a labeled "Show list" control (icon + text, not
      icon-only)
- [ ] [B] "Show list" returns to the 380px-list + reader layout in one click
- [ ] [B] × closes the reader; list returns to full width, scroll position intact
- [ ] [B] Reopening after close starts at 'normal' size again (full-width doesn't stick)

### Reader header
- [ ] [V] Read / Discuss segmented toggle; Discuss side shows a message-count chip when
      a thread exists
- [ ] [V] "N of M" position counter matches the article's place in the CURRENT
      filtered/sorted list
- [ ] [B] Prev (˄) / Next (˅) chevrons move through the current filtered order; counter
      updates; list highlight follows
- [ ] [B] Prev on the first article / Next on the last clamps (no wrap, no crash)

### Reader content — three stacked sections (replaced the Content/AI Summary tabs, 2026-08-02)
- [ ] [V] Spinner while content loads, then: type badge, content-type chip (when set),
      "domain · date" line, "N min read"
- [ ] [V] Title at 20px bold
- [ ] [V] "WHY IT MATTERS · PRIORITY n" amber callout — only when the article has one
- [ ] [V] **SUMMARY** section: labeled header with divider line, digest text in a card
- [ ] [V] **APPLICATION ANALYSIS** section: accent-tinted card — ONLY on articles that
      have one (tier-2); absent on summary-only articles (absence is correct)
- [ ] [B] **FULL ARTICLE** section, first open: spinner + "Fetching full article from
      <domain>…", then the real scraped article text renders (markdown)
- [ ] [B] FULL ARTICLE, reopening the same article: text appears instantly (disk cache
      in `fulltext_cache/`, no re-fetch)
- [ ] [B] FULL ARTICLE, fetch failure (paywall/dead link): amber notice with working
      **Retry** and **Open original ↗** actions; retry actually re-attempts
- [ ] [V] FULL ARTICLE on an article with no source URL: "nothing to fetch" note
- [ ] [B] Navigating prev/next mid-fetch never shows article A's full text under
      article B (stale-fetch guard)
- [ ] [B] No Content/AI Summary tabs anywhere anymore — one continuous scroll
- [ ] [V] Long articles scroll inside the reader pane (header stays put)

### Reader action row (icon-only, mirrors list-row style)
- [ ] [B] Discuss icon → switches to Discuss mode
- [ ] [L] Open-original icon → source URL in a new tab (hidden when no source)
- [ ] [B] Favorite / Archive toggles — reflect and update the same state as the list row
      (toggle in reader, confirm the list row's star/border updates too)
- [ ] [B] Send to HomeLab — same spinner-in-slot + toast behavior as the list row,
      including the inert checkmark once sent
- [ ] [B] Resubmit — same toast/queue behavior as the row menu
- [ ] [B] Delete → inline "Delete this article? Yes, delete / Cancel" (not a modal)
- [ ] [V] There is deliberately NO flag-duplicate button in the reader (dropped
      2026-08-01; the row's ⋯ menu still has it — absence here is correct, not a bug)

---

## 9. Reader pane — Discuss mode

### Entry & layout
- [ ] [B] Entering Discuss auto-expands to full width — including from an
      already-open normal-size reader (a fixed bug: it used to only widen from 'normal')
- [ ] [V] Split layout: article prose on the left (read-only, no action row), 520px chat
      panel on the right with its own border
- [ ] [B] Scrolling down through the article (left pane) does NOT move the chat panel —
      the article scrolls in its own pane, chat and reader header stay pinned
      (fixed 2026-08-02: refreshable wrapper was breaking the height chain)
- [ ] [B] Same in Read mode: long articles scroll under the pinned reader header, and
      the page as a whole never scrolls
- [ ] [B] Switching back to Read keeps the current size; article content still there

### Model picker & grounding chips
- [ ] [V] Claude / Agy / Local 3-way toggle; active model tinted in its own color
      (Claude accent, Agy amber, Local green)
- [ ] [B] Switching models mid-thread is allowed and the next reply uses the new model
- [ ] [V] "This article" chip: lock icon, no on/off dot, not clickable
- [ ] [V] "Article archive" chip: ON by default, shows live "N saved" count
- [ ] [V] "homelab-infra" chip: OFF by default, shows live "N files" count
- [ ] [B] Turning the repo chip ON opens a popover anchored under the chip: "Repo
      access", names homelab-infra, states it only reads on turns you ask; "Got it"
      dismisses it (chip stays on)
- [ ] [B] Chip on/off states persist per-article (leave, come back, still set)
- [ ] [V] Grounding footer line under the input names the active sources + model

### Thread
- [ ] [V] Empty thread: "No messages yet" + suggested-prompt pills. Guide/tutorial/
      reference articles get setup-comparison prompts; everything else gets
      summarize/relate prompts
- [ ] [B] Clicking a suggested prompt sends it as a real message
- [ ] [B] Typing + Enter sends; the ↑ send button also sends; empty/whitespace input
      is ignored
- [ ] [V] User messages: right-aligned accent bubbles. Assistant: left-aligned card
      bubbles with markdown rendering
- [ ] [V] While waiting: spinner + thinking line that names the ACTIVE sources, e.g.
      "Claude is reading this article, your archive + homelab-infra…"
- [ ] [V] Tool-call pills above a reply: bolt icon, monospace tool name, detail text,
      green check
- [ ] [V] Repo citations: expandable `path:line` block with a monospace snippet
- [ ] [B] Archive citations: expandable, and "Open «title»" navigates the reader to that
      cited article (in Read mode)
- [ ] [B] ⚙ Threads are per-article: article A's conversation, sources, and count chip
      never appear on article B (the pre-v2 leak — verify it's dead)
- [ ] [B] Thread survives leaving the page and coming back (persisted to disk)
- [ ] [B] Row's comment-count chip and the Discuss tab's count chip increment as
      messages are added
- [ ] [B] "Clear thread" empties the conversation AND removes the row's comment chip;
      suggested prompts return
- [ ] [B] Error from the model surfaces as an "Error: …" assistant message, not a hang

---

## 10. Keyboard shortcuts (from the list; must NOT fire while typing in any input)

- [ ] [B] `?` opens the cheat sheet; sheet lists all 11 bindings; Close works
- [ ] [B] `j` / `↓` and `k` / `↑` move the highlight; clamps at both ends
- [ ] [B] **If the reader is open, j/k also navigate the reader** to the newly focused
      article (fixed 2026-07-31 — verify)
- [ ] [B] If the reader is closed, j/k only move the highlight (do NOT open the reader)
- [ ] [B] `Enter` opens the focused article
- [ ] [B] `x` enters select mode and checks the focused row
- [ ] [B] `r` / `f` / `a` toggle read / favorite / archived on the focused row
- [ ] [B] `s` sends the focused row to HomeLab
- [ ] [B] `Del` / `Backspace` starts the inline delete confirm on the focused row
- [ ] [B] `Esc` clears the highlight and cancels any pending inline delete confirm
- [ ] [B] With a cursor in the search box, tag box, or Discuss input, letters type
      normally (no accidental archive/delete)

---

## 11. Cross-cutting & integrations

- [ ] [B] Nav unread badge, header stats, and folder counts all agree with each other
      after any sequence of actions
- [ ] [B] AI assistant sidebar (wand icon, separate from Discuss) knows the intake
      context: current folder/search, visible articles, and the open article's content
- [ ] [V] AI sidebar context card shows the newspaper icon, "N visible" pill, and the
      open article's title
- [ ] [B] Sort + density prefs and per-article Discuss sources/threads all survive a
      full service restart (stored in `intake_state`, not memory)
- [ ] [B] Two browser tabs open at once: actions in one don't crash the other
      (second tab may need a reload to see changes — that's acceptable; a crash is not)
- [ ] [B] Leave the tab idle ~10 min, come back, click things — no dead UI /
      "Connection lost" loop (the 2026-07-30 stability fix)

---

## Known stubs & deferred — expected behavior, don't file as bugs

| Item | Expected |
|---|---|
| Add URL / Run intake buttons | Info toast only — no backend yet |
| Library button + `⌘K` | "Later phase" toast — deferred with the query-builder |
| Dedicated tag-filter UI (TODO.md) | **⏸ ON HOLD** with all §3 tag-dropdown testing |
| Reader below ~1400px total width | No responsive fallback — desktop-first |
| Discuss token streaming | Full reply appears at once — intentional |
