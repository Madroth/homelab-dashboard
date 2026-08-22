# Article Intake "Design v2" — Manual Testing Guide

For Chris to drive in a real browser — everything below has only been verified
headlessly (`test_intake_fixes.py`, 54 tests) plus a full 6-tab boot check against
real data. Nothing has actually been *looked at* yet.

## 0. Before you start

```bash
systemctl --user restart homelab-dashboard.service
journalctl --user -u homelab-dashboard.service -f   # watch for startup errors
```
NiceGUI runs with `reload=False` — none of today's changes are live until you
restart. Open the dashboard and go to the **Article Intake** tab.

Log any bug you find with: what you did, what you expected, what actually happened.
Doesn't need to be formal — a screenshot + one line is plenty.

---

## 1. Global nav (affects all 6 tabs, check this first)

- [ ] Rail shows three labeled groups: **WORKSPACE** (Dashboard, Article Intake, Mod
      Pipeline, Media Curator), **INFRASTRUCTURE** (System Status, Containers,
      Network, Settings), **SERVICES** (Crafty Controller, Plane, Freqtrade)
- [ ] Article Intake shows a live unread-count badge; open an article and mark it
      read (press `r` or click the read icon) — badge count should drop by 1
      *without* switching tabs or refreshing
- [ ] Mod Pipeline's existing pending-count badge still works
- [ ] Containers and Network are visibly disabled (greyed out, not clickable)
- [ ] Crafty Controller / Plane / Freqtrade each open in a **new tab**, correct URLs
- [ ] Click the collapse arrow at the top of the rail — collapses to a slim icon-only
      strip; hover each icon and confirm a tooltip names it (this is the fallback for
      Crafty Controller's icon, which was changed from a cube to a gamepad so it
      doesn't look identical to Mod Pipeline's icon at a glance — check those two
      specifically look distinguishable)
- [ ] Expand the rail again — same group layout, correct tab still highlighted
- [ ] Switch between all 6 tabs — each still renders, nothing else regressed
- [ ] Reload the page with a tab selected — URL's `?tab=` still restores it

## 2. Article Intake — toolbar & filtering

- [ ] Header line reads real numbers: "N articles · N unread · N archived · queue N"
      — spot-check these against what you can see in the list
- [ ] **Search** — type a term that matches a title; list narrows. Clear it via the
      × on the filter chip below the toolbar (not just backspacing the text) —
      confirm the search box itself visibly empties too
- [ ] **Folder/status dropdown** — click it, confirm you see: All, Favorites,
      Duplicates, Archived, then a divider and any custom folders you have, then
      "+ New folder". Each shows a count. Selecting one closes the menu and filters
      the list
- [ ] **Tag dropdown** — click it, select **two or three tags in a row** without
      closing the menu in between — this is the one piece of UI that needed a
      workaround to stay open across multiple clicks, so it's worth specifically
      confirming it doesn't snap shut after the first tag. Type in the tag search box
      to narrow the list. Click "clear N" to reset
- [ ] **Sort dropdown** — cycle through all 5 modes (Unread first, Newest, Priority,
      Title A-Z, Favorites first) and confirm the list order actually changes each
      time
- [ ] **Density toggle** — switch Cozy → Compact: rows get noticeably tighter, badge
      row simplifies, snippet disappears. Switch back
- [ ] **Select mode** — click "Select", checkboxes appear on rows, bulk action bar
      appears once you check at least one
- [ ] Filter chips row shows a removable chip for each active filter (folder, each
      tag, search term) plus "Clear all" — confirm "Clear all" actually resets
      everything in one click

## 3. Archiving — the core semantic change this round

This is the one thing we spent the most time deciding, so it's worth testing
deliberately rather than just in passing.

- [ ] Archive an article from the **All** view (archive icon on the row, or press
      `a`) — it disappears from All immediately
- [ ] Open the **Archived** folder (from the dropdown) — the article you just
      archived is there
- [ ] Un-archive it from within the Archived view — it disappears from Archived and
      reappears in All
- [ ] **Favorite an article, then archive it.** Confirm it disappears from All, but
      is *still visible* under **Favorites**. This is the specific scenario that
      drove the whole design decision (an article you favorited shouldn't vanish
      just because it later got archived, e.g. by Send to HomeLab)
- [ ] Find (or create) a **duplicate-flagged** article, archive it. Confirm it's
      still visible under **Duplicates** despite being archived
- [ ] If you have a custom folder with an article in it: archive that article,
      confirm it's still visible in that custom folder
- [ ] Confirm there's **no more "Include archived" checkbox** anywhere in the
      toolbar — Archived is purely a dropdown destination now

## 4. Row actions (both in the list and in a bulk selection)

- [ ] **Read/unread** toggle — icon and title weight/color change immediately
- [ ] **Favorite** toggle — star fills/empties
- [ ] **Archive** toggle — see §3
- [ ] **Send to HomeLab** — click it, confirm you see a spinner in that same slot
      *immediately* (not after a delay), and it resolves to either a success toast
      (article becomes read + archived) or a failure toast. Check the actual Plane
      project to confirm the to-do was really created
- [ ] After that send, the control is a **green checkmark** — it never sends again.
      Reload the page — still a checkmark, and pressing `s` on that article toasts
      "Already sent to HomeLab." instead of sending again
- [ ] Now delete that to-do in Plane and click the checkmark: it should clear, the send
      control should come back, and you should get "That to-do no longer exists in
      HomeLab — you can send again." This is the only way back from a to-do deleted in
      Plane — before it existed, the article was stuck as "sent" forever
- [ ] **Delete** (single row) — click it: the row's action icons should swap in
      place to "Delete? Yes / No" — **not** a popup/modal. Click No, confirms it
      cancels and the row returns to normal. Click Yes on a throwaway test article,
      confirm it's actually gone
- [ ] **⋯ overflow menu** — open it on a row, confirm all five items work: Open
      original (new tab), Discuss with AI (opens the reader straight into Discuss
      mode), Move to folder, Flag as duplicate / Clear duplicate flag (label should
      match the article's current state), Resubmit

## 5. Bulk actions

- [ ] Select 2-3 articles, try each bulk button: Mark read, Mark unread, Favorite,
      Archive, Unarchive, Move to folder, Delete
- [ ] **Bulk delete should show a confirmation modal** (unlike the single-row inline
      confirm) — this was a deliberate choice, confirm it's actually there
- [ ] Select some articles, then switch folders — selection should clear
      automatically (not carry over to the new folder's rows)

## 6. Reader pane

- [ ] Click an article — reader opens on the right, list narrows to a fixed width and
      the reader fills the rest of the window (no blank space on a wide monitor)
- [ ] **Scroll partway down a long article list, then click an article roughly in
      the middle of your scroll position.** This is the specific bug an external
      review caught and I fixed — confirm the list does *not* jump back to the top
      when the reader opens. This is the single most important thing to check in
      this whole guide
- [ ] Click the expand icon — goes full width and the list hides entirely, with a
      "Show list" label (not just a small icon) to get back — click it to snap
      straight back to the list+reader layout
- [ ] Use the prev/next chevrons in the reader header — moves to the adjacent
      article in your current filtered/sorted list, and the "N of M" counter updates
- [ ] ~~Content / AI Summary tabs both render something~~ REPLACED 2026-08-02: reader
      now stacks SUMMARY / APPLICATION ANALYSIS / FULL ARTICLE sections — see
      `INTAKE_FEATURE_CHECKLIST.md` §8 for the current checks
- [ ] "Why it matters" callout shows when the article has one
- [ ] Reader's own action row (Discuss, Open original, Favorite, Send to HomeLab,
      Archive, Flag duplicate, Resubmit, Delete) — spot check a couple, especially
      that Delete here is also the inline Yes/No style, not a modal
- [ ] Click the × in the reader header — closes it, list returns to full width

## 7. Discuss mode

- [ ] From the reader, click the "Discuss" tab — it should auto-widen if you were at
      normal size, and split into article-on-left / chat-on-right
- [ ] "This article" chip has a lock icon, not clickable
- [ ] "Article archive" chip is on by default; "homelab-infra" (repo) chip is **off**
      by default
- [ ] Click the repo chip to turn it on — a small popover should appear naming
      "homelab-infra" specifically and stating it only reads on the turns you ask,
      nothing runs in the background. Click "Got it" to dismiss
- [ ] Try a suggested starter prompt, or type your own question — confirm you get a
      real reply, and that the "thinking" state names what it's reading (e.g. "Claude
      is reading this article + your archive…")
- [ ] If the assistant uses a source, confirm a tool-call pill appears above its
      reply, and any citation (repo or archive) expands correctly
- [ ] **Switch to a different article, enter Discuss there, then switch back to the
      first article's Discuss thread** — confirm the two threads and their source
      toggles are independent (this used to leak between articles before today,
      should be fixed now)
- [ ] "Clear thread" removes the conversation for that article

## 8. Keyboard shortcuts

Press `?` for the cheat sheet, then check each one works from the list (not while a
text box has focus):
- [ ] `j`/`k` or arrows move the highlighted row — **and if the reader is already
      open, it should follow along to the newly-focused article** (this used to not
      update the reader before today)
- [ ] `Enter` opens the focused row
- [ ] `x` enters select mode and checks the focused row
- [ ] `r` / `f` / `a` toggle read / favorite / archived on the focused row
- [ ] `s` sends the focused row to HomeLab
- [ ] `Del`/`Backspace` triggers the same inline Yes/No confirm as the delete icon
- [ ] `Esc` clears the focus highlight, and also cancels any inline delete-confirm
      that's currently showing

## 9. Empty/loading states

- [ ] Reload the page — briefly see a loading skeleton (shimmering placeholder rows)
      before real articles appear
- [ ] Filter to something with no matches (a nonsense search term, or a tag
      combination nothing has) — confirm a clear message + "Clear filters" link
- [ ] Failed queue items (if any exist) show at the top of the list area, red-tinted,
      with per-item Retry and a "Retry all" option

---

## Known gaps — don't report these, they're tracked separately

- **"Add URL" and "Run intake" buttons** in the header just show a toast saying
  they're not wired up yet — no backend exists for either.
- **"Library" button** shows a "coming in a later phase" toast — the saved-search/
  query-builder window from the original design spec was deliberately deferred, not
  built this round.
- **No `⌘K` shortcut** — same reason, it's the Library window's shortcut.
- **Narrow windows**: the reader's wide/full-width modes don't have a responsive
  fallback below roughly 1400px of combined width. Fine on a normal desktop monitor;
  worth flagging only if you actually use this from a small laptop screen.
