# Monitoring / Lab Health — Brief for Claude Design

Single self-contained reference for a Claude Design session designing the Homelab
Dashboard's monitoring surface. **This document intentionally contains no aesthetic or
visual direction** — no colors, fonts, spacing or style guidance. All graphic and
aesthetic decisions are Claude Design's to make. Everything below is functional/product
context: what the page is for, what data really exists behind it, what must never be
shown, and which features are live versus gated.

Companion docs in this repo: `DESIGN_BRIEF.md` (whole-dashboard product context and the
other five tabs), `IMPLEMENTATION_GUIDE.md` (service-layer contracts).

**Governing docs outside this repo — read these, they constrain the design more than
anything in this file:** `~/HomeLab/MONITORING.md` (the reasoning: failure classes,
outcomes, anti-goals, alert routing) and `~/HomeLab/MONITORING-COVERAGE.json` (the
inventory: 27 subjects, their checks, channels, root fixes). The build sequence lives in
`~/HomeLab/projects/homelab-monitoring/BUILD_BACKLOG.md`.

---

## 1. The one job

There is a recorded acceptance test for this page. It is the whole point, and every
layout decision should be judged against it:

> **O9 — One place to look.** *Done when:* someone unfamiliar can answer "is anything
> broken right now?" from a single URL in **under 30 seconds**.

Not "shows a lot of information about the lab." A stranger, one screen, thirty seconds,
a yes-or-no answer. If a design forces reading a dozen tiles to work out whether anything
is wrong, it has failed the test no matter how much it displays.

The second job is smaller and concrete, from `BUILD_BACKLOG.md` Phase 0.8: monitoring's
own tools (Uptime Kuma, Dozzle) currently have no home in the dashboard — their only
entry point is a quick-link parked on the **Media Curator** page, pointing at a service
that page no longer owns.

## 1a. What the page is for — and what it is not

Chris, 2026-08-22: the dashboard is where he looks at *everything* and investigates
further. So this page's job is **surfacing errors and drilling into them** — full error
text, readable and copyable, and a path from "that is red" to "here is what it says and
what to run". Not a wall of green tiles offering reassurance.

The corollary matters as much: **this page is not a detector, and must not be designed as
if it were.** MONITORING.md's one principle — *a detector may not depend on the health of
the thing it monitors* — explicitly excludes dashboards, and Uptime Kuma ran for months
with a perfectly good UI and zero monitors while seven failures went unseen. Detection is
the phone's job (ntfy). This page is what you open once you already know, or when you go
looking. Design it as an investigation surface, not an alarm.

## 2. Why this lab is unusual, and what it means for the design

On 2026-08-15 an audit found **seven failures that had been running silently for days or
weeks**. Backups that had never once succeeded. A NAS mount down since a reboot. A remote
model host dead for two days. A container that had restarted 3,000 times.

The tooling was not missing — Uptime Kuma was running the whole time with zero monitors.
The defect was that **everything failed open**: when a check could not do its job, it
reported success. The single governing principle that came out of it:

> **A detector may not depend on the health of the thing it monitors.**

Two consequences that are *design* problems, not backend problems:

- **A green tile must never be the default state.** "I could not determine this" has to be
  visually distinct from "this is fine" — at a glance, not on inspection. This is the most
  important instruction in this brief. There is already a precedent in this codebase: the
  System page used to read the root SSD's free space when `/mnt/Multimedia` was unmounted
  and display a healthy number, and it did so for three days before anyone noticed.
- **Freshness is part of the state.** A check that passed 6 months ago is not passing. The
  registry expires verification at **90 days** (`defaults.verify_max_age_days`). A tile
  showing "OK" with a stale timestamp is the exact failure mode this project exists to
  remove, so staleness needs to be visible on the tile itself, not in a tooltip.

## 3. Constraints

Built in **NiceGUI** (Python, renders to Vue/Quasar), not hand-written HTML/React —
whatever comes out of this session gets translated into NiceGUI components afterward.

- Prefer standard layout patterns (flex rows/columns, cards, grids, tables, chips, modals,
  tabs) over bespoke CSS/JS-heavy interaction.
- **Data refresh is polling on a timer, not websockets.** Design nothing that assumes a
  live push stream. Refresh is on-demand or periodic; a manual refresh affordance is fine.
- One user (Chris), desktop-first, driven from a browser tab left open. Not a phone app —
  **phone is where alerts go, via ntfy; the dashboard is where you look.** Do not design a
  notification centre that competes with the phone.
- Design against the real data shapes in §6, not placeholder content. The registry schema
  there is real and current.
- The global nav already reserves two disabled placeholder items: **Containers** and
  **Network** (`components/nav_sidebar.py:20-21`). A monitoring page could claim one, sit
  as a new item, or absorb the existing **System Status** tab — see §8.

## 4. What exists today

**In the dashboard** — `pages/system.py` renders `services.system.get_status()`, which is
the closest thing to this page and covers perhaps a fifth of it:

- a DEFCON banner (a list of critical strings: mount down, <5% free, Gluetun collapsed,
  media-curator daemon inactive)
- `docker ps -a` container cards, colored from the container's own `Status` string
- `/mnt/Multimedia` disk usage — and an explicit `NOT MOUNTED` error state that refuses to
  report a number when the mount is absent
- Plex's memory line from `docker stats` (the only container it reads)
- a log tail via `get_logs()`

**Running in the lab** — 54 containers, 37 up, across 13 compose projects: `plane-app`
(13), `asf-data-warehouse` (12, dev-only and exempt), `media-curator` (11), `gamelab-wotlk`
(5), `homelab-monitoring` (4), plus `open-webui`, `ntfy`, `nocodb-jobhunter`, `homepage`,
`freqtrade`, `crafty`, `context-server`. Alongside them, 28 hand-authored systemd user
units (services and timers) inside a user manager holding 85 loaded services in total.
**The media stack is under a fifth of the lab — a page built around it will not scale.**

**The monitoring tools themselves**, owned by `homelab-monitoring` since 2026-08-22:
Uptime Kuma (`http://100.87.245.107:3001`), Dozzle (`http://100.87.245.107:8888`),
socket-proxy, autoheal. Self-hosted ntfy at `http://100.87.245.107:5001`.

**The registry** — `MONITORING-COVERAGE.json` holds 27 declared subjects, 12 root fixes
(8 still open), 2 channels, 5 check profiles, and an `exempt` list with expiry dates.
**Every check in it is currently `state: "planned"` — nothing is live yet.** Worse for the
design: only **8 checks exist across all 27 subjects**, so most subjects carry an empty
`checks` list. 19 of 27 are `unreviewed`. The page must therefore be designed to look
*correct and useful* while showing almost entirely "planned/unverified/nothing declared",
and to fill in without redesign as checks go live. A layout that only looks right when
populated will look broken for months.

## 5. Anti-goals — do not design these

Recorded in `MONITORING.md` with reasoning, after two predecessor projects died of exactly
this over-reach. Treat these as hard boundaries:

- **No Prometheus / Grafana / time-series database.** Not one of the seven failures was a
  metrics problem; every failure class is *binary* — it ran or it didn't, it's mounted or it
  isn't. A metrics stack would have caught **zero** of them.
- **No line charts of CPU/memory over time.** There is no time-series store to draw them
  from, and building one is explicitly out of scope. If a design needs a sparkline to make
  sense, the design is wrong for this lab.
- **No per-container CPU/memory alerting** — "noise without a decision attached".
- **No log-aggregation alerting.** Log scraping is how the existing broken watchdog worked,
  and a clean silent failure emits no error text to scrape. (Reading logs on demand is
  fine — that is what Dozzle is for.)
- **No auto-remediation controls beyond container restart.** Restarting a container with a
  bad config just loops faster.

If one of these later becomes necessary it is a new decision with new evidence, recorded as
an ADR amendment — not something a UI design introduces by drawing it.

---

## 6. Real data shapes

### 6a. The registry — `MONITORING-COVERAGE.json`

**This is the page's primary data source and the key to it scaling.** The page should
render the registry rather than a hand-built list of services: a new subject declared there
becomes a new row with no UI work. There are 27 subjects today and the nightly reality-diff
(O8) exists specifically to add more.

```python
subject = {
  'id': 'plane-backup',                      # dict key
  'kind': 'systemd-timer' | 'systemd-service' | 'docker-service' | 'docker-stack'
          | 'mount' | 'remote-endpoint' | 'unknown',
  'identity': {'manager': 'user'|'system', 'unit': str, 'schedule': str},  # shape varies by kind
  'owner_project': str,                      # e.g. 'plane-shared-work-management'
  'criticality': 'critical' | 'important' | 'routine',   # 7 / 12 / 8 today
  'includes': ['backup-job'],                # profile names; check bundles, one level deep
  'state': 'planned' | 'unreviewed' | 'live',
  'checks': [check, ...],
}

check = {
  'id': 'plane-backup.heartbeat',
  'failure_class': 'FC-1',                   # FC-1..FC-9, see 6b
  'asserts': str,                            # human sentence: what must be true
  'detector': {'tool': 'uptime-kuma'|'self-report'|..., 'type': 'push', 'grace_s': 93600},
  'alert_channel': 'ntfy-self:homelab-alerts',
  'severity': 'critical' | 'warn' | 'info',
  'state': 'planned' | 'live',
  'verified': None | {'at': str, 'method': str},   # None = never proven. Expires at 90 days.
  'runbook': str,                            # shell one-liner or path to a doc
  'blocked_by': 'RF-1' | None,               # a root fix standing in the way
}

channel = {
  'kind': 'ntfy' | 'ntfy-public',
  'endpoint': 'http://100.87.245.107:5001/homelab-alerts',
  'subscribed_by': [],                       # EMPTY today — a channel with no named human
                                             # is not a channel. This is a first-class alarm.
  'state': 'planned' | 'deprecated',
  'note': str,
}

root_fix = {
  'id': 'RF-1',
  'finding': str,                            # what was found broken
  'disposition': 'redesign' | 'fix' | 'accept',
  'action': str, 'done_when': str,
  'status': 'open' | 'done',                 # 8 of 12 open today
  'owner': 'Chris' | 'ClaudeCode',
  'blocks_checks': ['plane-backup.heartbeat', ...],
}

remote_host = {                              # omega, qnap1, qnap2, steamdeck, kitchen
  'last_manual_review': str | None,          # None = never reviewed
  'review_interval_days': 90,
  'subjects': [str, ...],
  'access': str, 'note': str,                # qnap2 is OFF-LIMITS — never probed, by policy
}

exempt = {'by_rule': [{'match_kind', 'match', 'reason', 'review_after'}, ...]}
ratchet = {'unreviewed_subjects_max': 19, 'open_root_fixes_max': 8}   # may only shrink
```

### 6b. Failure classes — the vocabulary the UI should speak

Every check declares one. Grouping or filtering by these is more useful than grouping by
service type, because they map to what a human does next.

| ID | Class | Note for the UI |
|---|---|---|
| FC-1 | Scheduled job failed, or never ran | Absence within a grace window is the signal |
| FC-2 | Job succeeded but produced nothing useful | Asserts on the artifact, not the exit code |
| FC-3 | Unit flapping / restart loop | **A flapping container reads as *up* on ~half of any naive poll** — a green dot is actively misleading here; this needs a restart-count delta |
| FC-4 | Unit failed and stays failed | "Is anything in a failed state" across both systemd managers — cheapest, highest-yield check in the design |
| FC-5 | Mount missing | Path is genuinely a mountpoint |
| FC-6 | Silent wrong-target write | Canary file that exists only on the real remote volume |
| FC-7 | Remote dependency dead while its host is alive | **Check the service, never the host** — a ping's green light is misleading |
| FC-8 | The alert path itself is broken | Needs a named human per channel and a periodic canary |
| FC-9 | Resource exhaustion, trending | Threshold **and** rate-of-change |

### 6c. What the dashboard can already compute — `services/system.py`

```python
status = {
  'defcon': [str, ...],        # critical strings, empty when nothing is wrong
  'containers': [ {...docker ps -a --format json...} ],   # Names, Status, Image, State
  'disk': {'total','used','free','free_pct'} | {'error': '/mnt/Multimedia is NOT MOUNTED'},
  'memory': {'plex': str},
  'daemon_active': bool,
}
```

Cached with a short TTL. Note the `disk` union: **it is either a reading or an error, never
a fallback number.** Any new tile that reads a resource must keep that shape.

---

## 7. The feature list

Ordered in tiers by what blocks them. **Tier 1 is the only tier with nothing standing in
its way** — design it as a complete, shippable page on its own, with the later tiers as
space the layout can grow into rather than a promise it depends on.

### Tier 1 — Ships now (Phase 0.8; no dependencies)

| # | Feature | Detail |
|---|---|---|
| **F1** | **A monitoring home** — its own section or page | The deliverable of Phase 0.8. Everything else hangs off it |
| **F2** | Launcher for the monitoring tools | Uptime Kuma `:3001`, Dozzle `:8888`, ntfy `:5001`. Open in a new tab. These are full apps — the dashboard links to them, it does not reimplement them |
| **F3** | Container health, whole-lab | Already computable today from `docker ps -a`. Must scale to 54 containers across 13 compose projects — **grouping by compose project is the natural axis**, not one flat list. Media is one group of thirteen |
| **F4** | Failed-unit floor | "Is anything in a failed state" across both systemd managers. One number, prominent; drill-down to which. Highest-yield single check in the whole design. **It is not zero right now** — as of 2026-08-22: `plane-backup.service` (user, the RF-1 backup that has never succeeded), `livescore.service` and `snap.tailscale.tailscaled.service` (system). Design against three failures, not against an empty state |
| **F5** | Mount truth, fail-closed | `/mnt/Multimedia` and the phantom `/mnt/qnap2`. Mounted / not mounted / **unknown** — never a plausible number from another disk |
| **F6** | Root + NAS capacity | Threshold state, not a graph. "Over the line" or not, with the number |
| **F7** | Quick-link decision | The Uptime-Kuma link on Media Curator (`pages/media.py:28`) points at a service that page no longer owns. Design where it belongs; a deliberate decision either way is what Phase 0.8 asks for |

### Tier 2 — The O9 answer (Milestone M7 "Surfacing")

| # | Feature | Detail |
|---|---|---|
| **F8** | **The verdict** | One unmissable answer to "is anything broken right now?" — the 30-second test lives or dies here. Needs at least four states: **all clear / degraded / broken / cannot tell**. The fourth is not optional |
| **F9** | Subject list, rendered from the registry | All 27, filterable by kind, criticality, state and failure class. This is what makes the page scale — new subjects appear without UI work |
| **F10** | Coverage honesty | Per subject: is it covered, and when was that last *proven*. `state: 'unreviewed'` (19 today) and `verified: null` must read as gaps, not as blanks |
| **F11** | Staleness | Verification expires at 90 days. A tile whose proof has expired is not green |
| **F12** | Open root fixes | 8 of 12 open, each with an owner and the checks it blocks. These are the "we know this is broken and it is not being watched" list — arguably the most valuable thing on the page today |
| **F13** | Alert-channel health | `subscribed_by` is **empty** — by the project's own rule, that means there is no channel. Surface it loudly; this is FC-8, the class that made the other seven invisible |
| **F14** | Drift / undeclared subjects | Output of the nightly reality-diff (O8): anything running that the registry does not know about |
| **F15** | Remote hosts | omega, qnap1, qnap2, steamdeck, kitchen — with `last_manual_review` and its expiry. **qnap2 must render as deliberately off-limits, never as unknown-and-should-be-checked** |
| **F16** | Runbooks | Every check carries one. Surfacing it next to a red state is what turns the page from information into action |

### Tier 3 — Gated on M1 and M2 (the monitors themselves)

**M1 is a hard gate: no monitor may be built before the alert channel it fires into is
proven.** These are what the page fills with once checks go live. Design the containers for
them; do not design a page that looks broken without them.

| # | Feature | Detail |
|---|---|---|
| **F17** | Live check state per subject | The `state: 'planned' → 'live'` transition across 27 subjects |
| **F18** | Heartbeat freshness (FC-1) | Every scheduled job proves it ran, within a grace window. Absence is the signal |
| **F19** | Restart-delta / flapping (FC-3) | A counter, not a liveness dot |
| **F20** | Backup assertions (FC-2, O3) | Artifact age and size vs trailing median, plus **restore-test age** — restorability, not execution. Sourced from the backup job's self-report; QNAP2 is never probed |
| **F21** | Remote dependency checks (FC-7) | Omega's model server at the service layer, never a ping |
| **F22** | Channel canary (FC-8) | A periodic test alert a human must actually acknowledge, and whose *absence* alerts |

### Tier 4 — Designed-for, explicitly not yet approved

| # | Feature | Detail |
|---|---|---|
| **F23** | **Device resource thresholds** | This is Milestone **M8**, and it **requires an ADR 26 amendment before it may be built** — it collides with the "no per-container resource alerting / no TSDB" anti-goal. The compatible reading, if it is taken: **binary thresholds only** — over the line or not, no history, no graphs, accepting that "when did it start climbing" is unanswerable. Memory PSI (`/proc/pressure/*`) is a genuine uncovered gap and fits binary thresholds cleanly. **Design a slot this can occupy; do not design charts for it.** |
| **F24** | Other devices | Omega, Steam Deck, kitchen. The hard part: this box cannot enumerate them, and Omega is RDP/Taildrop-only by deliberate decision. Any device-level check needs an agent or endpoint on that device — a new *access* decision, not a monitoring one. Whatever is shown must carry an expiry, because it is a claim rather than a fact |

### Candidate subjects not in the catalog

Things a healthy homelab usually watches that this one has not declared. **They are not
approved** — each needs a registry entry, and some need an ADR. Listed so the layout is
built to absorb new subject *kinds*, not so tiles get drawn for them now:

- **Disk SMART health** — `smartd` is already a declared subject (`state: planned`), and
  `MONITORING.md` records that its alerts currently mail into a mail system that does not
  exist on this host. Closest to real of anything in this list.
- **DNS resolution** — the hostname `qnap2` does not resolve, which is half of why RF-1's
  backup has never succeeded. A resolution check is a binary fit.
- **Time sync** — heartbeat grace windows are meaningless if the clock drifts.
- **Container image / update drift** — 54 containers on `:latest` tags.
- **Certificate expiry** — low value *here*: services are HTTP over Tailscale, not TLS on
  the public internet. Do not design a cert panel without evidence it is needed.
- **UPS / power** — unknown whether one exists.
- **An external dead-man** — recorded as an open, unsolved problem: *the monitoring system
  cannot alert on its own death*. It needs something outside this host. The page can state
  this limit honestly; it cannot solve it.

---

## 8. Design decisions we need from this session

1. **Where does this live?** Absorb the existing **System Status** tab, claim the reserved
   **Containers** nav slot, or add a new item? System Status already does ~20% of the job,
   so two overlapping pages is the outcome to avoid.
2. **How does one screen carry 27 subjects, 54 containers and 12 root fixes without
   becoming a wall?** Progressive disclosure is expected — the 30-second answer on top,
   detail underneath.
3. **What is the primary grouping** — compose project, failure class, criticality, or
   "broken first"? Filtering can offer the rest.
4. **How are the four verdict states distinguished**, especially "cannot tell" versus
   "all clear"? This is the design's central problem.
5. **How is staleness shown** without a timestamp on every row shouting at once?
6. **What does an almost-entirely-"planned" page look like** so it reads as honest coverage
   gaps rather than as a broken page?

## 9. What not to design

- Anything from §5's anti-goals — charts over time above all.
- A reimplementation of Uptime Kuma or Dozzle. Link to them; they are better at their jobs.
- A phone/notification centre. Alerts go to ntfy on the phone; this is the place you look.
- Controls that mutate infrastructure beyond a container restart.
- Any tile that shows a number it cannot actually source. Fail closed, always.

## 10. Acceptance

- A stranger answers "is anything broken right now?" in under 30 seconds. (O9)
- Unmounting the NAS produces a visible error state, never a plausible number. (O5)
- Monitoring has a home listing Uptime Kuma and Dozzle, and a recorded decision on the
  Media Curator quick-link. (Phase 0.8)
- The page reads as honest with every check `planned` — today's real state.
- A subject added to the registry appears with no redesign.
