# Homelab Dashboard TODOs

- [x] **AI Assistant Sidebar Integration**
  - [x] Add a collapsible tab to the right side of the screen.
  - [x] Implement a chat interface allowing interaction with an LLM.
  - [x] Provide a model selector to switch between Claude, Agy, and a local model.
  - [x] Give the LLM context of what the user is currently looking at on the dashboard.
  - [x] Grant the LLM capabilities/tools to discuss the dashboard state, make changes to the dashboard, and manage the homelab.

- [x] **Media Stack (Backend & Security)**
  - [x] Deploy 15-container stack (Plex, *arrs, VPN).
  - [x] Enforce strict Gluetun Killswitch on qBittorrent.
  - [x] SRE Hardening (Docker Socket Proxy, Autoheal labels, Resource Limits).
  - [x] Wire live monitoring into Dashboard (DEFCON banner, container states).

- [ ] **Game Server control panel — reactivation from the dashboard** (Chris, 2026-09-01)
    - Context: the WoW realm (gamelab tenant `wotlk`) and the Minecraft server
      (`crafty-minecraft`) are both deliberately stopped to free resources. They cost
      real headroom while idle — measured 2026-09-01: WoW ~5.5 GiB and ~100% of a core
      with 40 playerbots and nobody playing, Minecraft ~950 MiB and ~100% of a core.
      Bringing either back currently means a terminal and knowing the commands.
    - [ ] An area on the dashboard listing the game servers with their current state,
      and a control to start one back up.
    - [ ] Starting must be **asynchronous with progress**, not a button that blocks.
      A WoW cold start takes minutes: the client-data init and world-DB import run
      before the worldserver is ready, and "container running" is *not* "playable".
    - [ ] Show when it is genuinely ready, not merely started. gamelab's tenant
      contract already declares how to tell (`health.type: log_marker`, container
      `ac-worldserver`, marker `ready...`), so the dashboard should surface whatever
      gamelab reports rather than inventing its own check.
    - [ ] Show the cost of turning it on — slice memory in use against its ceiling —
      since the whole reason these are off is resource headroom.
    - **Status 2026-09-11: 4b is closed** (gamelab `0e91a38`, 2026-09-09). `start`,
      `switch` and `restore` now wait for the tenant's `log_marker`, printing progress, and
      `gamelab list` has a READY column. **What is still missing is machine-readable
      output.** Everything gamelab offers is text for a human: no `--json`, no status file,
      no API. The clean contract exists inside gamelab (`health.probe()` returns
      `Readiness(state, detail, elapsed)`, state `ready/waiting/failed/unknown/timeout`) but
      is not exposed. Parsing the table would break the first time a column moves. That
      already happened to homelab-monitoring's collector, which reads the tenant name from
      column 2 and, once READY was added, fired a false critical for a tenant called
      `playable`. They fixed it in `d924686` by importing gamelab's Python instead.
      Importing gamelab over `sys.path` is exactly the `services/media.py` coupling this
      repo regrets. **Asked 2026-09-11: gamelab `docs/OPEN-WORK.md` item 11** requests
      `list --json` and `status <tenant> --json`. `start --no-wait` already exists, so the
      dashboard can start a tenant and poll readiness. Buildable once item 11 lands.
    - **Original dependency note:** see gamelab `docs/OPEN-WORK.md` item 4b. The dashboard should call gamelab, not shell out to
      `docker` itself: starting a tenant has to go through `gamelab _up`, which is where
      the pending-neutralise safety check lives. A second start path that skips it would
      reintroduce a hazard that took real work to close.
    - Note only one game tenant may run at a time (`slots.capacity: 1`), so the UI is a
      *switch* between servers more than independent on/off toggles.

- [ ] **Article Intake — backlog moved from homelab-intake (2026-09-11).** Intake's
  Milestone C (its `BUILD_BACKLOG.md` Phases 8–10) was always work on this page; Chris ruled
  that intake sticks to the pipeline, so it lives here now. Product decisions that came with it:
  `docs/INTAKE_ARCHITECTURE.md §9`.
  - [x] **Phase 8 — list, card, detail view.** Done 2026-09-11. "Read Next" as the landing
        view was dropped: the list lands newest first (`43f42e2`), priority is a sort option.
  - [ ] **Phase 9 — smart folders.** A saved query (tag filters + sort, maybe content_type)
        that auto-populates. *Done when:* a saved smart folder picks up a newly processed
        matching article with no manual step. The index already carries every field it would
        filter on; nothing is needed from intake. Faceted browse and the Archive view exist.
  - [ ] **Phase 10 — digest view.** An auto-generated "your week in saves" view. *Done when:*
        it renders the week's articles. (The chat half of Phase 10 largely exists as
        `components/discuss_panel.py` with citations — check it against "answers from the
        corpus with clickable citations" before building anything.) A pushed digest
        *notification* would be intake's (its `DESIGN.md §10`), not this page's.
  - [ ] **"Analyze this" button** — forces Tier-2 analysis on a filed article. The button is
        this page's; the force path is intake's Phase 11, so it waits on that.
  - [ ] **Human review of the tag editor and Education view.** Tag editor reviewed by Chris
        2026-09-11 ("looks good"); the tag-search box closing on every keystroke he found
        there is fixed (`25331e5`). Education view not confirmed.
  - [x] History carried over from intake's TODO, both done 2026-07-08: the Resubmit button,
        and card-clutter trimming (AI-preamble stripping, the `###` truncation fix, 3-tag cap).
  - Note: the **Tag Filtering** item below predates the tag menu (`render_tag_dropdown`,
    multi-tag AND filter, searchable list), which now exists. Probably closable.

- [ ] **Article Intake (Tag Filtering)** — ⏸ ON HOLD (Chris, 2026-08-02; revisit later)
  - [ ] Add a dedicated tag-filter UI to the article intake tab — tags currently only match via the free-text search bar, no way to browse/filter by tag directly.
  - [ ] Decide on presentation (filter chips, tag cloud, etc.) alongside the existing Homelab/News/Errors folder sidebar.

- [ ] **Article Intake — investigate (noted 2026-08-04, from Chris's live testing)**
  - [x] **Fixed `a329de8`.** Reader's action icons went stale after workflow toggles: clicking Favorite (from
    either the list row or the reader itself) updates the list row's highlight
    immediately, but the reader pane's own star doesn't repaint until something else
    rebuilds the reader (switching articles, opening Discuss, etc.). Cause is visible in
    `pages/intake.py`: `toggle_read`/`toggle_favorite`/`toggle_archived` call
    `_refresh_after_workflow_change()` (list row) but never `render_reader.refresh()`
    when the toggled article is the one open in the reader. State on disk is always
    correct — purely a repaint gap. Applies to the reader's Read/Archive icons too, and
    now also bites in Discuss mode since the action row shows there as well (2026-08-04
    change). Fixed inside `_refresh_after_workflow_change()` rather than in each of the
    three toggles, so a fourth cannot forget it. Two regression tests, both confirmed
    failing against the old code.
  - [x] **Fixed `a329de8`.** Failed queue entries gave no way to read/copy the error: clicking the entry
    just retries it, and the error text only exists as a hover tooltip ("RETRY n/3").
    Clicking now opens the full text — selectable, copyable, with the attempt count —
    and Retry moved one click further in. (Noted 2026-08-04 while triaging the
    Omega-unreachable failures.)

- [ ] **Monitoring / lab health home on the dashboard (2026-08-22)** — one place to see
  whether the lab is healthy, rather than the pieces scattered across pages. Merged from
  two notes written the same day: Chris's ask for a single health/status/usage/alerts/errors
  surface, and the fallout from the Phase 0.7 move.

  Uptime Kuma, Dozzle, socket-proxy and autoheal moved out of `media-curator`
  into the `homelab-monitoring` project on 2026-08-22 (HomeLab BUILD_BACKLOG.md
  Phase 0.7). The dashboard has no surface of its own for them: the only entry
  point is the Uptime-Kuma quick-link parked on the **Media Curator** page
  (`pages/media.py:28`, `static/index.html:209`), which now points at a service
  that page no longer owns. Dozzle (`:8888`) has no link at all.

  The other half already exists but only partly: `pages/system.py` renders
  `services.system.get_status()` — a DEFCON list (mount down, <5% free, Gluetun collapsed,
  media-curator inactive), `docker ps` container cards, `/mnt/Multimedia` disk usage, Plex's
  memory line, and `get_logs()` for a log tail. Decide whether that page becomes this home
  or sits beside it.
  This was the original wishlist, written before P0 existed. Reconciled against the code
  2026-08-29 — four of the six are delivered; the two that are not say what is missing.
  - [x] **Done `ba101fa`.** Monitoring has its own page rather than borrowing another
        project's: `pages/lab_health.py`, linking Uptime Kuma `:3001`, Dozzle `:8888` and
        ntfy `:5001` (`pages/lab_health.py:24-26`).
  - [x] **Decided and done `ba101fa`.** The Media Curator quick-link moved rather than
        staying — Chris's call 2026-08-22; Kuma is not a media service. `pages/media.py`
        no longer mentions it.
  - [x] **Done `e8189a0` (2026-09-09).** Rolled up to the list: five states derived from
        `docker ps`, with "running, unchecked" as its own answer for a container that
        declares no healthcheck — up, and nothing verified it. Group headers count the
        states out instead of "N/M up".
  - [x] **Done `5cb1694` (2026-09-09).** The last two gaps closed with F14: host uptime,
        and Tailscale reachability at the service layer rather than by ping. Units, load,
        the NAS mount and disks were already there.
  - [x] **Done `2bf4b9c`.** Resource usage: host CPU, memory, disks and temperature with
        kernel pressure, plus per-container `docker stats` fetched on drill-down rather
        than only for Plex. Nothing is retained — the bounded ring buffer in P2 is the
        ceiling and is still to come.
  - [x] **Done `ba101fa`.** Error reporting: journald errors from both managers, failed
        units and non-zero container exits, merged and collapsed by repeat, with the full
        text selectable and copyable. Subsumed the intake failed-queue complaint above.

  **Sequencing decided 2026-08-22 (Chris). Most of this waits for the monitors.** The
  design work is done and parked: `docs/MONITORING_BRIEF.md` (24 features in four tiers,
  grounded in `~/HomeLab/MONITORING.md` and the coverage registry) plus a four-artboard
  canvas at https://claude.ai/code/artifact/162c3a93-1e9b-431f-bd0f-6d8458e04532. Do not
  redo either; do not build against them yet.

  Why it waits: 0 of 8 declared checks are live, so there is no check *output* to design
  against — what a live check returns (status, last-run, error text, grace countdown) is
  settled by M1/M2 and determines the subject table more than any layout choice does. The
  build backlog says the same thing under "Suggested cut lines": **"Defer freely: M7"**,
  and M7 is this. Anything registry-driven — subject table, coverage/staleness, check
  states, root-fix list — waits for real checks.

  **Chris's framing for what the page is for (2026-08-22):** the dashboard is where he
  looks at *everything* and investigates further — so its job is surfacing errors and
  drilling into them, not reassurance. It is deliberately NOT a detector: under
  MONITORING.md's one principle a dashboard cannot be one, and Uptime Kuma ran for months
  with a fine UI and zero monitors while seven failures went unseen. Detection is the
  phone's job (ntfy, M1); investigation is this page's.

  **Feature backlog: `docs/LAB_HEALTH_FEATURES.md`** (2026-08-22) — P0–P4 in priority
  order, from Chris's framing that the page is for looking at everything and investigating
  further. P0–P3 are all derived-on-read from this box (docker / systemd / /proc / journald)
  and depend on `homelab-monitoring` for nothing; only P4 waits.

  What does NOT wait:
  - [x] **Phase 0.8 — done `ba101fa`.** Monitoring has its own home: the System Status tab
        became **Lab Health** (`pages/lab_health.py`, tab key still `system` so `?tab=`
        links survive), linking Uptime Kuma `:3001`, Dozzle `:8888` and ntfy `:5001`.
        The Kuma quick-link **moved off Media Curator** — Chris's call, 2026-08-22: it is
        not a media service and that stack stopped owning it at Phase 0.7. (`static/index.html`
        still has a Kuma link at :209, deliberately untouched — that file is dead legacy.)
  - [x] **F1 error stream + F4 units — done `ba101fa`.** journald errors from both managers,
        every failed unit, and containers exited non-zero, merged and collapsed by repeat;
        click for the full copyable text plus the command to dig further. Units list with
        state, restarts and a per-unit log tail. All readers fail closed (`{'ok': ...}`),
        so an unreadable source renders as "cannot tell", never as a quieter list.
        Suite 73 green.
  - [x] **F2 + F3 — done `2bf4b9c`.** P0 is complete. Containers group by compose project
        and open to state, their own healthcheck verdict, live `docker stats`, ports, mounts,
        output and a Dozzle link. Resources replaced the old three-card grid: CPU load,
        memory, disks and temperature, each clickable, with kernel pressure (PSI) on CPU and
        memory and swap exhaustion leading the memory card. Every card has a "cannot tell"
        face. Suite 100 green.
  - [x] **P1 done `d9f5567` + this commit.** F6: every panel stamps when it was read,
        `get_status()` stamps before its cache stores it so a cache hit cannot restamp,
        and the stamps age on their own 5s timer so a dead poll shows amber instead of
        freezing at the last good reading. F5 was already in place. F7: one box filters
        errors, units and containers, and cannot make the lab look healthier than it is —
        global verdict, an amber "you are looking at a slice" banner, "showing N of M",
        and an explicit no-matches state. Suite 100 → 110.
  - [x] **P2 done.** F11: a 60-sample in-process ring buffer, dropped on restart, never
        persisted and never alerted on. Sampling is demand-driven, so the trend reports
        the span it actually covers rather than a nominal five minutes, collapses
        simultaneous reads from several tabs into one reading, and refuses a direction
        below three readings or 60s of span. F10: an error detail now shows neighbouring
        errors within ±5m sorted by proximity, plus the resource range retained around
        then — and says "nothing was retained" rather than implying calm. Suite 110 → 124.
  - [x] **F14 done.** Reachability: the NAS mount probed by an actual bounded filesystem
        call rather than `ismount()`, with mounted-but-unresponsive, not-mounted and slow
        as three distinct answers; endpoints checked at the service layer with
        reached-but-unhappy kept apart from did-not-answer; tailnet state filtered to lab
        peers. It feeds the verdict, so a dead service cannot sit under a green banner.
        Host uptime landed with it, closing the second P1 leftover.
  - [x] **P3 complete 2026-09-09.** F13 SMART read from smartd's own world-readable
        attribute log (no root needed, wakes no disk, and it is exactly the record whose
        alerts are being lost); an attribute a drive does not publish is unknown, never
        zero. F15 backups read from systemd rather than a self-report nobody would
        maintain. F16 reads HARDWARE.md so the dashboard is wrong exactly when the
        canonical doc is; everything is a dated claim except tailnet reachability, and
        QNAP2 renders as off-limits by policy rather than as a coverage gap.
  - [ ] P4 stays parked on registry-driven work — needs real check output from
        `homelab-monitoring`. **Rechecked 2026-09-11, still parked.** That project now has
        real runtime alerting: 8 Prometheus rules and 4 Loki rules, all evaluating, and
        Alertmanager live on `:9093`. But `~/HomeLab/MONITORING-COVERAGE.json` still lists 0
        of 18 checks as `live`, and nothing links a firing rule back to a registry subject
        or check id. Their Block 3.1 (registry drives the rules) is what creates that link,
        and it is unbuilt. Something buildable now, if wanted: an *active alerts* panel read
        from Alertmanager's API. It is real and stable enough, but it is not P4.
  - [x] **Done 2026-09-09.** Per-container health rolls up to a service-level verdict.
        A container with no declared healthcheck reads "running, unchecked" — Chris's
        call — as a hollow outline rather than a filled box, and does not count as broken
        in group ranking or in the AI sidebar's context.

- [ ] **Local model host — interim substitution, needs a real answer (2026-09-01)**
  Omega's Ollama stopped answering and the AI sidebar's local-model path died with it. The
  dashboard now points at the **local** Ollama on this box instead. That is a stopgap chosen
  deliberately over building failover, and it has real costs recorded below.

  **What happened.** `100.74.2.92:11434` refused to complete a TCP handshake while
  `tailscale ping Omega` returned in 0s — host up, service dead. On Omega itself
  `http://localhost:11434` was also unreachable, so it was not a firewall or an `OLLAMA_HOST`
  binding problem: Ollama simply was not running. Found by F14 the day it was built, entirely
  by accident, which is the part that should worry us — see "detection" below.

  **What we substituted.** `services/ai/chat.py` now defaults to `http://172.17.0.1:11434`,
  the local instance, bound to the docker0 bridge so containers reach it at the gateway. It
  has ~19 GB of models already on disk and had been running untouched for 8 days.

  **What it costs, measured not guessed:**
  - Local inference is **CPU-only and stays that way**. The GTX 680M is Kepler, compute
    capability 3.0, under Ollama's 5.0 floor; the last driver branch supporting it (470.xx)
    is EOL and will not build on this kernel. Ollama logs `offloaded 0/13 layers to GPU`.
    No amount of driver work changes this — it is below the supported floor, not misconfigured.
  - Only `mistral:7b` and `qwen2.5-coder:7b` advertise the `tools` capability, and the sidebar
    needs tool calling. `phi3:mini` and `gemma2:9b` cannot do it at all.
  - Speed: `phi3:mini` managed 5.4 tok/s; the 7B tool-capable models are far slower again.
    Omega did 39 tok/s on a 32B. So the sidebar is now usable for short exchanges and
    frustrating for anything longer, and a 7B answers worse than a 32B besides.

  **The better solution, to design later — do not just leave the stopgap in place:**
  - [ ] Stop hardcoding one host. An ordered candidate list (Omega, then local) with a cached
        reachability probe is the shape; F14's `probe_endpoint`/`get_reachability` already does
        exactly this check, so the machinery exists and only the policy is missing.
  - [ ] Decide the routing rule once there is a choice again: small/cheap work local, anything
        long or accuracy-sensitive on Omega. "Offload the minor things" was Chris's framing.
  - [ ] Model identity is not portable across hosts. `DEFAULT_OLLAMA_MODEL` was a 32B that does
        not exist locally, so pointing the host elsewhere without changing the model would have
        failed with a model-not-found rather than falling back. Whatever replaces this has to
        carry host *and* model together.

  **Not this project, but the reason this bit us:** nothing detected Omega's absence. The
  dashboard found it by accident while building an unrelated feature, and it had been down long
  enough that nobody could say when it started. A check for Omega's Ollama belongs in
  `homelab-monitoring`'s registry, and with M1 closed there is now a phone to tell. Recorded
  here only as the cause; the work is theirs.

  **Omega's own fix is Chris's:** Ollama on Windows runs as a tray app tied to a login session,
  not a service, so a reboot with nobody logging in takes it down silently and will do so again.
  Running it as a real Windows service is the durable fix.

- [ ] **Send to HomeLab — hardening (2026-08-18)** — full plan and findings live in
  `homelab-intake/TODO.md` ("Send to HomeLab + its support systems"); this is the
  dashboard-side slice of it. Four fixes are committed (`f489f8f` label failure no longer
  sinks the send, `181752e` toasts survive a handler refreshing its own row, `6fffbc5`
  issue id recorded + read back + checkmark, `ca6334c` idempotent resend via Plane's
  `external_id` — a repeat POST returns 409 with the id Plane already holds, proven against
  live Plane — plus a catch-all so nothing unexpected escapes the send and leaves the row's
  spinner turning forever). Suite green at 48; pushed and live on the running service as of
  2026-08-22. Still open here:
  - [x] Reconcile recorded `plane_issue_id`s against Plane so a to-do deleted there clears
    the article's checkmark. Clicking the checkmark re-checks that one to-do
    (`plane.issue_status()`, three-valued so an unreachable Plane can never be read as
    "deleted"); gone clears the flag and restores the send control. This also closed a
    dead end the hardening pass had created: nothing cleared `plane_issue_id`, and the
    control it drives refuses to resend, so a to-do deleted in Plane left the article
    permanently unsendable short of hand-editing `intake_state.json`.
  - [x] **Done 2026-09-09.** A picker in the intake header chooses where the next to-do
        lands, listing the workspace's projects with the `.env` default first. The
        load-bearing part is not the dropdown: `plane_issue_id` now travels with
        `plane_project_id`, because `issue_status()` may CLEAR that link when it reads
        'gone', and an issue in another project answers 404 from the default one —
        indistinguishable from deleted. Without recording the project, the first re-check
        of an article sent elsewhere would orphan a live to-do and mark it unsent.
  - [x] **Closed 2026-09-11 as not needed — built, then removed the same day.** "A sent
        article's to-do is write-once" was never a request. Traced back, it was a bare
        bullet written 2026-08-22 (`e0ea2ff`) by a session tidying this file: a description
        of a limitation, with no reason attached. It was then copied into STATUS.md,
        homelab-intake's triage and the handoffs until it read as "the only unblocked feature
        left". The 2026-08-18 investigation it supposedly came from never mentions it.
        It was built (`14ae6d3`, *refresh, never clobber*, proven once against live Plane: one
        comment on the DockTail to-do, nothing else changed). Then Chris asked when he would
        ever need it. The only case is resubmitting an article *after* sending it, since
        Resubmit rewrites title and summary in place. He removed it: "I can't imagine
        needing it." Reverted with `67109d7`'s icon and click fix. If it ever comes back,
        `14ae6d3` has the design, including the finding that Plane rewrites
        `description_html` on save, so any "was it edited?" check must fingerprint what Plane
        stores, not what was sent.

- [ ] **media-curator coupling — a change over there landed today that reaches in here (2026-08-22)**
  `services/media.py` does `sys.path.append('/home/linuxbox/projects/media-curator')` and imports
  that repo's internals directly: `database.get_conn`, `library.approve_item`/`reject_item`,
  `curator_daemon.identify_media`, `DROP_ZONE`, `is_contained`. No package boundary, no version
  pin, so a refactor there breaks this with no compile-time or test-time signal. That risk stopped
  being theoretical today.

  **What changed in media-curator (commits `1ebc6f4`, `8e817d3`):**
  - `queue.db` gained an `alert_state` table and `PRAGMA user_version` migrations. `get_conn()` is
    unchanged, so nothing here breaks — but this repo is now the **third writer** to that database
    (daemon, this app, and this app's AI assistant tool).
  - `check_exists(original_path)` is now `check_exists(original_path, file_hash=None)` and matches
    on status as well as path. It also **raises** on a database error instead of returning `False`.
    Nothing here calls it today — that was checked — but it is the bridge to watch.
  - The `UNIQUE` index on `original_path` was **dropped**, replaced by a partial unique index over
    `(original_path, file_hash)` that applies only to `pending` rows.
  - Two new statuses exist: `superseded` and `rejected_kept`. `static/app.js` filters explicitly on
    `'pending'`/`'approved'`, so neither renders in the active list — correct by luck, not design.

  - [x] **`undo()` fixed — `93aaaa4`.** It was worse than "would 500": the file moved
        *before* the unguarded `UPDATE`, so an `IntegrityError` against the new partial index
        left the file in the drop zone while the row still said approved at `proposed_path` —
        filesystem and database permanently out of sync, from a button press. The file is now
        moved back before the error is reported, the connection closes on every path, and a
        failure to restore says so naming both paths rather than stranding the file silently.
        (Found by agy's 2026-08-22 review of the week; confirmed against the code.)
  - [x] **Tests — `a329de8`.** The "zero tests" note was wrong: `pages/media.py` already had
        5 page-level tests. Added 3 more covering the gap that mattered — a service failure
        reaching the user rather than arriving as nothing — plus the 4 undo tests on the
        service side. `test_media_fixes.py` is at 12.
  - [x] **Done 2026-09-09.** `reclassify()` degrades with the missing symbol named, and
        the Rejected folder shows what awaits deletion while omitting rows whose files
        are already gone.
  - [x] **Done 2026-09-09 — `services/media_backend.py`.** One declared surface of five
        symbols, a named failure instead of a bare ImportError, a `check()` following the
        reader contract, and tests that fail if `services/media.py` imports those modules
        directly again or reaches for something undeclared. The coupling itself remains —
        only media-curator can remove it — but it is now explicit and loud.
        *Original note:* name what this app actually needs from
        media-curator (approve, reject, reclassify, identify, the drop zone) and depend on
        that surface instead of reaching past `sys.path` into its internals — so a refactor
        over there fails loudly here. Doable from this repo alone against today's imports;
        it does not wait on media-curator publishing anything. Whether *they* expose a real
        package is theirs (their Epic 7, unowned) and is not tracked here.

- [x] **Fixed `a329de8` — `test_toggle_select_timing_with_large_queue` was flaky (2026-08-22)** — it asserts a
  wall-clock budget (`< 0.5s`) and fails intermittently on a loaded machine. Measured on clean
  `HEAD`, unrelated to any change: 2 of 3 consecutive runs failed. A timing threshold in a test
  suite that shares a host with a game server and a media daemon will keep doing this. Either
  raise the budget substantially, mark it as a benchmark that does not gate the suite, or
  measure work done rather than seconds elapsed. **Took the third option:** it is now
  `test_toggle_select_rebuilds_one_row_not_the_whole_queue`, asserting via element identity
  that the toggled row was rebuilt and the other 79 were not. Five consecutive green runs.

---

- [x] **Fixed `2a19f3f` by the homelab-intake session, then corrected here `9fd2061`.**
  The rewrite reads the index and falls back to parsing only for files the index does not
  cover, so it cannot return a short list. Reviewing it found the two paths were not in
  step: `_article_from_row` served `raw_content` in original case while the file path
  lowercases it, and `pages/intake.py:307` searches it with an already-lowered term — so
  body-text search silently missed every capitalised word, for every indexed article. Four
  tests now hold the invariant the docstring only asserted. *Original finding:*
  homelab-intake's CLAUDE.md is explicit: "SQLite is a derived index... The dashboard reads
  the index, never the files directly." `services/intake.py:list_articles()` instead globs
  `articles/*.md` and parses every one. Measured on the live corpus: **1,579 ms to parse 119
  articles (13.3 ms each), against 6.1 ms to pull the same metadata from
  `index/articles.db` — 257x.** It degrades linearly: ~6.6 s at 500 articles, ~13 s at 1,000.
  The `_articles_dir_signature()` mtime cache hides it (1 ms warm) but the full cost is paid
  again whenever *any* article file changes, which now includes every in-place reprocess.

  This is not simply a shortcut that can be swapped out — **the index does not carry what
  the dashboard needs**: `snippet`/body, `raw_content` (which backs full-text search across
  the whole corpus), `reading_minutes`, `user_folders`, `auto_generated`. That is the real
  finding: the schema in `homelab-intake/docs/DESIGN.md §5` and the dashboard's actual needs
  have diverged, and reading the files is the workaround that has been papering over it.

  Two honest options, and this is Chris's call, not a refactor to be done quietly:
  1. **Extend the index** to carry those fields (full-text search wants SQLite FTS5, which
     is the right tool and would be *faster* than the current scan, not merely compliant).
     Per homelab-intake's CLAUDE.md the schema contract changes in `docs/DESIGN.md §5`
     **first**, then propagates to pipeline, index and dashboard.
  2. **Amend the constraint** to say the dashboard reads the index for list/filter metadata
     and the files for body content, which is roughly what a corrected implementation would
     do anyway. Cheaper, and honest about the split.

  Doing nothing is also a position, but it should be a chosen one: the constraint currently
  says something the code does not do, which is how the next person gets misled.

- [x] **`test_media_fixes.py` fails intermittently under host load (found 2026-09-01).**
  **Explained and fixed 2026-09-11. It was a real page bug, not a harness timing problem.**
  The first step recommended below was taken: `conftest.py` now saves every failing run to
  `.test-failures/`. The very first captures showed the confirm and edit dialogs had
  *vanished* between the click and the next step. The mechanism: NiceGUI deletes a
  `ui.dialog()` when an invisible canary element, placed wherever the dialog was created,
  is collected. A dialog opened from a row click is created inside that row, and
  `pages/media.py`'s 5 s poll rebuilt every row whether or not anything had changed. So any
  poll landing while a dialog was open destroyed it, and the handler awaiting it hung. The
  same rebuild deleted a button between `find()` and `click()`, which covers the two approve
  tests. Under load a test straddles a poll more often, hence the load-dependence. On the
  live page, Edit Title vanished within five seconds mid-typing. It was demonstrated
  deterministically, 3 of 3 runs failing without any forced GC, before anything was changed.
  Four fixes, each with a test that fails without it:
  `components/page_dialog.py` anchors every dialog in the app to the page, and deletes it on
  close so nothing leaks; the poll skips data that has not changed; the media handlers use
  `capture_client()` (once the dialog survived, a bare `client_alive()` after the row rebuild
  read "tab closed" and skipped the refresh, the same trap `components/util.py` documents for
  intake); and repeating timers no longer fire at page open (`immediate=False`). NiceGUI's
  default made Media, Home and Lab Health run every reader twice, concurrently, on each page
  load. The media fixture also stubs `get_rejected` now. It had been reading the real
  media-curator DB and stat'ing rejected files on the NAS in every UI test.
  **Evidence under contention** (8 CPU burners at nice 10, tests at nice 19, load 11-24):
  the original code (`4e0a189`) failed in **15 of 15** runs, 37 failures across 6 tests:
  confirm dialog gone 18, edit dialog gone 7, double reload at open 8, poll rebuilt a row 2,
  approve lost 2. The fixed code failed in **0 of 15** (360 test executions). Same harness,
  same conditions, run back to back. This harness is harsher than ordinary load, which is
  why the old code failed far more often here than the 1-in-15 seen on 2026-09-09.
  The retry-budget raise in `conftest.py` stays as harmless, but it was never the mechanism,
  as the 2026-09-09 note below suspected.

  **Attempted 2026-09-09 and NOT fixed — the history, kept for the lesson.** The obvious
  hypothesis was NiceGUI's retry budget: `User.should_see` makes 3 attempts with a 0.1s
  sleep, so 0.3s for an async render to finish, which is a wall-clock assertion by another
  name. `conftest.py` now raises that default to 30 (override with `NICEGUI_TEST_RETRIES`),
  which is free on the passing path since both helpers return the moment the assertion
  holds. **But the evidence does not support it being the mechanism.** Measured with the
  test process deprioritised (`nice -n 19`) to simulate contention without loading a live
  game server: retries=3 gave 1 failure in 15 runs, retries=30 gave 1 failure in 21, and a
  controlled 12-run A/B at each setting produced **zero** failures either way. The change
  is kept as a defensible removal of a timing cliff, not as a fix.

  Two things for whoever picks this up. The failure was never captured — no run that failed
  had its output saved, so the actual mechanism is still unknown, and *that* is the thing to
  fix first: make a failing run record what it saw. And I repeated the exact mistake this
  item warns about, concluding "reproduced it" from a single failure in three runs, which
  the later 12-run batch then contradicted. A/B at least a dozen runs per side before
  believing anything here.

  *Original finding:* Three
  UI-timing tests — `test_approve_updates_row_and_stays_visible`,
  `test_a_failed_approve_tells_the_user_why`, `test_a_failed_reject_tells_the_user_why`, and
  `test_reject_removes_row_via_full_refresh_fallback` in some runs — fail as a group, then pass
  on a rerun. Confirmed **pre-existing and not caused by any change**: three consecutive runs of
  the *unmodified* file gave 12 passed, 12 passed, 3 failed, and three runs of the modified file
  gave 12/12 each time. It only appears when the box is loaded (observed at load average 20-26);
  at normal load the full suite is green at 151.

  The trap is that a single run proves nothing — I concluded "decisive, not flakiness" off one
  sample and was wrong. Anything diagnosing this needs repeated runs. Same family as the
  `test_toggle_select_timing_with_large_queue` flake fixed in `a329de8` (2026-08-22), so
  NiceGUI's `User` harness timing out under contention is now a repeat pattern here rather than a
  one-off, and probably wants a fix at the harness level rather than per-test.

- [ ] **A page fetched without a browser logs ~23 errors a minute later (found 2026-09-11).**
  Any HTTP GET of a page that never opens the websocket (curl, a link preview, an HTTP
  monitor) makes NiceGUI build the whole layout, all tabs, for a client that never
  connects. Every one-shot and immediate timer on it waits for that connection. When NiceGUI
  discards the client about 65 s later, the waits are released and each timer dies in
  `_get_context()`: `RuntimeError: The parent slot of the element has been deleted`, one per
  timer. Measured: one curl gave 23 errors at +65 s on today's code and 25 on `4e0a189`, run
  side by side on a loopback port. **It predates 2026-09-11.** It was never seen before
  because nothing fetched the dashboard without a browser, until the session's own
  post-restart curls (138 errors at 11:02). Two more single bursts (11:06, 11:37) came from
  a fetcher not identified. It breaks nothing, but these are ERROR lines in the journal, and
  Lab Health's error stream reads the journal. Options: a light `/healthz` route for probes
  and checks, so nothing needs to fetch a full page; and/or guard timer callbacks against
  a deleted parent, which is really NiceGUI's bug to fix upstream. **Until then: check the
  service with a browser or the journal, not curl.**

- [ ] **Reader handlers can lose a click while the article is loading (found 2026-09-11).**
  `capture_client()` at the top of an *async* handler runs a tick after the click. If the
  reader re-renders in that tick (the article body arriving), the capture itself raises and
  the click silently does nothing. A test caught exactly this on the since-removed Update
  to-do control, and its fix was to take the client from the click event
  (`lambda e, i=aid: handler(i, e.client)`), which NiceGUI evaluates synchronously while
  the slot is still alive. `send_to_homelab`, `verify_plane_todo` and the toggles still
  capture late. Not observed failing, but the mechanism is the same. Converting them is
  mechanical.

- [ ] **Lab Health: an alerts panel read from homelab-monitoring's Alertmanager (Chris,
  2026-09-11).** **Why:** two reasons, both shown by that day's events. (1) *Disagreements
  become visible.* `GamelabTenantVanished` fired a false critical for 13 hours overnight while
  Lab Health's own containers panel showed the tenant healthy. Side by side, it would have
  read as false in seconds. The reverse case, something Lab Health sees broken that nothing
  alerts on, is a coverage gap worth seeing too. (2) *One place to look*, without opening
  Alertmanager or scrolling ntfy history. **Decided:** only an *active* critical counts
  against the "Nothing is broken" banner; a suppressed one is shown, but it never keeps the
  banner red over a deferral Chris already made. Units monitoring has exempted
  (`MonitoringExemption` alerts, the same live source Alertmanager inhibits on) show as
  "known", not broken. If Alertmanager cannot be read, exemptions do not apply and the panel
  says so. Read-only: the dashboard still sends, silences and decides nothing. **Not P4**:
  it shows what is firing, not coverage, which still waits on homelab-monitoring Block 3.1.

## Not this project (pruned 2026-08-29)

Chris's call: this backlog tracks the dashboard only. Work on the services the dashboard
*looks at* belongs to the project that owns them. Recorded here so it is handed over rather
than dropped — none of it is tracked in this repo any more.

**→ `media-curator`** (its stack, its configuration; nothing below touches dashboard code)
- Connect Prowlarr indexers to Radarr & Sonarr.
- Link Radarr & Sonarr to qBittorrent via API keys.
- Claim the Plex server and configure library folders (`/data/media`).
- Whether media-curator exposes a real package/API instead of importable internals — its
  Epic 7, unowned. The dashboard-side half of that boundary *is* still tracked above.

**→ `homelab-monitoring`** (it owns detection and alerting; Kuma and ntfy moved there at
HomeLab BUILD_BACKLOG Phase 0.7)
- Uptime Kuma alert configuration. The old note said Discord/Telegram webhooks; M1
  standardises on self-hosted ntfy, so that item was stale as well as misplaced.
- Somewhere alerts land and can be acknowledged. This one was not just misfiled, it was
  against the rule: **the dashboard informs and investigates, it does not detect or alert.**
  A page you have to be looking at is not a detector. Alert delivery is ntfy's, and M1
  (subscribe a phone to `homelab-alerts`) is Chris's.

What stays here: rendering Kuma/Dozzle/ntfy quick-links, showing media-curator's queue on the
Media Curator page, and everything in `docs/LAB_HEALTH_FEATURES.md` — including P4, whose
screens are this dashboard's even though they wait on homelab-monitoring for check output.
