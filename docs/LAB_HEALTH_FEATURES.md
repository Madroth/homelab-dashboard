# Lab Health Dashboard — feature list, in priority order

What to build on the dashboard's monitoring page, ordered by value per unit of work.
Written 2026-08-22 from Chris's framing: **the dashboard is where you look at everything
and investigate further.** Click a container, see how it is doing. Click an error, see what
it says. Click a resource, see what is eating it.

Companion docs: `MONITORING_BRIEF.md` (the design/UI brief and real data shapes — hand that
to a design session, this is the build backlog); `~/HomeLab/MONITORING.md` (the monitoring
project's governing doc, which owns *detection* and constrains what this page may claim).

## The one thing to keep straight

**This page informs; it does not detect.** Detection is the phone's job (ntfy, owned by
`homelab-monitoring`). A dashboard cannot satisfy that project's governing principle — *a
detector may not depend on the health of the thing it monitors* — and Uptime Kuma ran here
for months with a perfect UI and zero monitors while seven failures went unseen.

That boundary is also what unblocks this work. Everything in P0–P3 below is **derived on
read** from this machine — `docker`, `systemd`, `/proc`, `journald` — so none of it waits
for `homelab-monitoring` to build anything. Only P4 does.

**Displaying a live value is not the anti-goal.** MONITORING.md rules out a time-series
database, trend charts and per-container resource *alerting*. Reading `docker stats` when
you click a container breaks none of that: it is a read, on demand, retained nowhere. Keep
that line and almost all of this is in bounds.

## What exists today

`pages/system.py` renders `services.system.get_status()`: a DEFCON string list, `docker ps`
cards colored from the container's own status text, `/mnt/Multimedia` usage, Plex's memory
line, and a `media-curator` journal tail. Nothing is clickable. Measured on this box while
writing this (2026-08-22, ~15:30):

| | |
|---|---|
| Containers | 54 total, 37 up, 13 compose projects |
| Units | 28 hand-authored user units; 85 loaded user services; **3 failed** |
| Root disk | 219 G, 55% used, 95 G free |
| NAS | 61 T, 66% used, 22 T free — CIFS `//192.168.1.213/Multimedia` |
| Memory | 15 Gi total, 11 Gi used, **3.5 Gi available** |
| Load | 1.85 / 1.59 / 1.45 |
| CPU package temp | 72 °C (one zone at 75 °C) |
| Errors, last 24h | 26 in the user journal; the system journal is repeatedly logging `CIFS: VFS: \\192.168.1.213 has not responded in 180 seconds. Reconnecting...` |

That last row is the argument for this whole page. The NAS is flapping **right now**, the
mount still passes a mountpoint check so it looks healthy, and nothing anywhere surfaces it.

---

# P0 — The spine

Four lists, each with a drill-down. This is the page; everything after it is refinement.

### F1 · Error & event stream, with detail on click
The headline feature, and the one thing that exists nowhere today. One reverse-chronological
list of *things that went wrong*, from four sources merged:

- `journalctl -p err` — both managers, with unit, timestamp and full message
- units in a failed state (`systemctl list-units --state=failed`, both managers)
- containers that exited non-zero, restarted, or were OOM-killed (`docker events`, `docker inspect`)
- the dashboard's own domains — intake queue failures, media curator, mod pipeline

Click an entry: full untruncated text, **selectable and copyable**, the unit or container it
came from, surrounding journal lines, and a runnable command to dig further. Filters by
source, severity and time window; a badge for repeats ("×14 in 20 min") so a flapping error
is one row rather than fourteen.

*This subsumes the 2026-08-04 intake complaint — failed queue entries whose error survives
only as a hover tooltip. Same need, solve it once.*

### F2 · Container list → container detail
All 54, grouped by compose project (media is 11 of them; `plane-app` is 13). Row shows name,
state, health, uptime, restart count. Click for a detail panel:

- **State** — running/exited/restarting, exit code, started at, restart count
- **Health** — the container's own healthcheck verdict (`.State.Health.Status`), which is
  *not* the same as "running"
- **Resources, live** — CPU %, memory used vs limit, network I/O, block I/O, PIDs, from
  `docker stats --no-stream`
- **Config** — image and tag, ports, mounts, compose project, restart policy
- **Logs** — recent lines inline, plus a deep link to Dozzle for the real log UI
- **Actions** — restart only, deliberately (see "Not building")

### F3 · Machine resources → resource detail
A compact row of host resources, each clickable:

- **CPU** — load average, per-core utilisation, and `/proc/pressure/cpu` (PSI). Click for
  top processes by CPU and which containers they belong to.
- **Memory** — used/available/swap, plus `/proc/pressure/memory`. **Currently 3.5 Gi
  available of 15 Gi**, which is tight enough to matter. Click for top consumers, and any
  OOM kills from the journal.
- **Disks** — root and NAS: size, used, free, percent, and inode pressure. Click for the
  biggest directories and recent write activity (`iostat` is installed).
- **Temperature** — package and zone temps from `/sys/class/thermal`. **72 °C now.**
- **Network** — throughput per interface, and the CIFS mount's health specifically.

PSI is the honest way to answer "is this machine actually struggling" without a metrics
stack: it is a pressure ratio the kernel already computes, no history required.

### F4 · Services & units → unit detail
The 28 authored user units and the system units that matter, not just `media-curator`. Row:
active state, sub-state, restarts, last run. Click for: full `systemctl status`, the last
exit code and reason, restart count with the flap warning, next scheduled run for timers,
and a journal tail scoped to that unit.

**Today this would immediately show `plane-backup.service`, `livescore.service` and
`snap.tailscale.tailscaled.service` failed — none of which the dashboard currently mentions.**

---

# P1 — Make it trustworthy — **DONE 2026-08-29**

Without these the spine is worse than nothing, because it will confidently show green.

### F5 · Fail closed, visibly, everywhere

> **Done.** Every reader in `services/system.py` returns `{'ok', ..., 'error'}` and the page has a dashed "cannot tell" face distinct from healthy and broken.
Every panel needs three outcomes, not two: **fine / broken / could not determine**, with
"could not determine" visually distinct at a glance. Never render a plausible number from a
fallback source. There is precedent: the System page read the root SSD's free space as the
NAS for three days. `services/system.py` already returns `{'error': ...}` instead of a
number for the disk — extend that shape to every reader.

### F6 · "As of" and refresh

> **Done `d9f5567`.** Every panel stamps its read time; `get_status()` stamps before its 8s cache stores it, so a cache hit reports when the data was read rather than when it was served. The stamps tick on their own 5s timer, so a poll that has died ages into amber instead of freezing at the last good reading. A reader with no read time says AS OF UNKNOWN.
Every panel states when its data was read, and a manual refresh exists. Polling with a stale
timestamp silently showing minute-old state is how a dashboard lies.

### F7 · Search and filter across everything

> **Done.** One box across containers, units and errors. It may hide rows but never make the lab look healthier: the verdict stays global, a filtered page carries an amber banner, each section reports "showing N of M", and no-matches is explicit rather than an empty calm.
One box: container name, unit name, error text, image, port. With 54 containers and 85 units,
scrolling is not navigation.

### F8 · Deep links out

> **Done `ba101fa`.** Uptime Kuma, Dozzle and ntfy in the header; Dozzle per container.
Dozzle for a container's logs, Uptime Kuma, ntfy, and the compose project's directory. The
dashboard should not reimplement a log viewer that already runs at `:8888`.

---

# P2 — Investigation quality — **DONE 2026-08-29**

### F9 · Copyable everything
Error text, container ids, unit names, and the suggested command — one click to clipboard.
This is the difference between a status page and an investigation tool.

### F10 · Correlation window

> **Done.** Neighbouring errors within ±5m sorted by proximity, plus the resource range the ring buffer retained. A collapsed run of repeats widens the window to cover the whole run. Both halves state their limits; for most historical errors the buffer holds nothing, and it says so rather than implying the machine was calm.
On any error detail: "what else happened around this time" — other errors, container
restarts, resource spikes in the same few minutes. The CIFS flap is the case in point: the
NAS timing out and media containers stalling are the same event seen twice.

### F11 · Short-window rates, without a database

> **Done.** 60 samples, in-process, dropped on restart. Sampling is demand-driven, so the trend reports the span it actually covers, collapses simultaneous multi-tab reads into one reading, and refuses a direction below 3 readings or 60s of span. A failed sub-reader enters as None, never a plausible zero.
A bounded in-process ring buffer (say 60 samples, ~5 minutes) so a detail panel can say
"memory 40% → 88% over five minutes" instead of only "88%". **Nothing persisted, nothing
queried, dropped on restart** — this is a live reading with a short memory, not a TSDB, and
it stays inside the anti-goal. It answers "is this climbing?", which a bare number cannot.

### F12 · Grouping and saved views
Group by compose project, by health, by "things I care about". The media stack is under a
fifth of this lab; a page organised around it will not scale.

---

# P3 — Breadth — **DONE 2026-09-09**

### F13 · Disk SMART

> **Done.** Read from smartd's world-readable attribute log, newest row only — no root, no disk wakeups, and it is the record whose alerts are being lost (`-m root`, no MTA). An attribute the drive does not publish is unknown, never zero.
`smartctl` is installed. Reallocated sectors, pending sectors, power-on hours, self-test
results. `smartd` currently mails alerts into a mail system that does not exist on this host,
so this is the only place they would be seen.

### F14 · Network & reachability

> **Done 2026-08-30.** `probe_mount()` makes a real bounded filesystem call instead of trusting `ismount()`; mounted-but-unresponsive, not-mounted and slow are three answers. Endpoints are checked at the service layer, with reached-but-unhappy kept distinct from did-not-answer, probed in parallel. Tailnet peers filtered to lab hosts. Feeds the verdict banner. QNAP2 is never probed and a test asserts it.
Tailscale state, the CIFS mount's real responsiveness (not just "is it a mountpoint"), and
whether key endpoints answer — Omega's model server at the service layer, never a ping.

### F15 · Backups view

> **Done.** From systemd's own record rather than a self-report convention. Sizes and contents are only ever what each job says about itself. QNAP2 never probed.
When each backup last ran, what it wrote, and how big — read from each job's own self-report.
**QNAP2 is never probed**, by policy; the backup job is the only sanctioned thing that talks
to it.

### F16 · Remote hosts

> **Done.** Reads ~/HomeLab/HARDWARE.md rather than copying it. Dated claims, except tailnet reachability which is checked; a host we cannot ask is never called offline. QNAP2 renders as off-limits by policy.
Omega, qnap1, steamdeck, kitchen — with an explicit "last reviewed" and an expiry, because
this box cannot enumerate them and anything shown is a claim rather than a fact. QNAP2 renders
as deliberately off-limits, never as unknown.

---

# P4 — Waits on `homelab-monitoring`

Everything registry-driven. There is no check *output* to display until M1/M2 produce some,
and its shape will decide these screens more than any layout choice: per-subject coverage,
check pass/fail state, proven-vs-planned, staleness against the 90-day expiry, open root
fixes, alert-channel health and routing. Design already exists for these in
`MONITORING_BRIEF.md` and the canvas — parked deliberately, not forgotten.

---

# Deliberately not building

- **No time-series database, no Grafana, no trend charts.** F11's ring buffer is the ceiling.
- **No alerting from the dashboard.** A page you have to be looking at is not a detector.
  Alerts belong to ntfy and the monitoring project.
- **No log-scraping alerts.** Reading logs on demand is the point; alerting on scraped text
  is how the previous broken watchdog worked.
- **No auto-remediation beyond a container restart.** Restarting a container with a bad
  config just loops faster.

# Cost notes for whoever builds this

- `docker stats --no-stream` across 37 containers takes ~1–2 s — too slow for a synchronous
  render. Fetch per-container on drill-down, or refresh the list asynchronously with a cache
  (`services/system.py` already caches with a TTL).
- `psutil` is **not** in the venv. Either add it to `requirements.txt` or read `/proc`
  directly; `/proc/pressure/*`, `/proc/loadavg`, `/proc/meminfo` and `/sys/class/thermal`
  need nothing extra.
- The journal is large — always bound queries by `--since` and `-p`, and paginate.
- `lm-sensors` is not installed; temperatures come from `/sys/class/thermal` only. There is a
  discrete GPU (GTX 680M) but it is unusable for compute — Kepler, compute capability 3.0,
  under Ollama's 5.0 floor — so there is no GPU telemetry worth reading either.
- Reads should stay off the main thread — the existing pages use `run.io_bound` for exactly
  this.
