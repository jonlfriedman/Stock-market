# Stock-market / Premarket Volume Scanner

## Infrastructure (read this first)

A **DigitalOcean droplet at `157.230.1.250`** was created to run the
premarket volume scanner continuously. This fact does not live anywhere
else durable — Claude Code sessions are ephemeral and only see this repo,
so if this file is ever deleted or not read, that context is lost again.
Do not assume the droplet is still running, reachable, or running any
particular branch's code without checking — ask the user or have them run
commands on it, since **sandboxed Claude Code sessions generally cannot
reach arbitrary IPs over SSH** (outbound is HTTPS-only through a proxy).

Known as of 2026-08-30 (confirmed by SSHing into the droplet directly):
- Droplet IP: `157.230.1.250`, Ubuntu 24.04, deployed at
  `/opt/premarket-scanner` per the README, systemd unit
  `premarket-scanner` (enabled, running as user `scanner`).
- **Deployed code is branch `claude/claude-code-env-ko2jgj`, commit
  `e817265`** ("Add one-off script to recover a lost baseline from the
  CSV log") — this is the from-scratch two-phase rebuild line, **not**
  PR #1's fixes (Finviz RVOL column bug fix, downward-price gate,
  price-outcome tracking). Those PR #1 fixes are not on the droplet.
- Service has been `active (running)` since **Thu 2026-08-27 06:53:46
  EDT**. That restart timestamp lines up with the last deployed commit
  being a baseline-recovery script — something broke around Aug 27 and
  was patched; the root cause hasn't been dug into yet (check
  `journalctl -u premarket-scanner` around that time before trusting
  data spanning the restart).
- Real data exists at `/opt/premarket-scanner/data/`: `scanner.db`
  (SQLite, alert history) and `data/logs/scan_2026-08-25.csv` through
  `scan_2026-08-28.csv` (Tue–Fri, a few MB each). This is the first
  confirmed evidence the scanner actually ran and logged premarket data.
  Contents (alert count, whether triggers fired, data quality) have not
  yet been analyzed — do that before treating a week of data as "in
  hand."
- The `.env` on the droplet (Finviz/Pushover credentials) has not been
  inspected and shouldn't be pasted into chat — treat as a black box,
  just confirm it exists if debugging.

When asked "is the scanner running" / "did it collect data" / "where are
we with the scanner": do not answer from git history alone. Have the user
run diagnostic commands on the droplet (or get you SSH access some other
way) and update this section with what's confirmed, including the date.

## Branch situation (as of 2026-08-30)

Everything forks from commit `5a8f83d` ("Correct Finviz export URL
instructions..."). No `main`/`master` branch exists in this repo — only
`claude/*` branches. Two independent, unreconciled follow-up lines exist:

1. **PR #1** (open, mergeable clean, no CI configured) — branch
   `claude/premarket-volume-scanner-bs43ru`: Twilio→Pushover swap, Finviz
   RVOL column-name fix, drops RVOL from scoring, adds a downward-price
   discard gate, adds price-outcome tracking (15/30/60 min post-alert)
   and a `review_alerts.py` script.
2. **`claude/claude-code-env-ko2jgj`** (no PR opened) — a separate
   from-scratch rebuild ("two-phase build spec"), also Twilio→Pushover,
   plus baseline persistence across restarts and a baseline-recovery
   script. Does not include PR #1's RVOL fixes or outcome tracking.

These two branches both touch the same Twilio→Pushover change but are
otherwise incompatible rewrites. Nothing has reconciled them, and neither
is confirmed to be what's running on the droplet.

## Repo layout

- `premarket_scanner/` — the scanner package (Finviz client, scoring,
  storage, alerts).
- `deploy/premarket-scanner.service` — systemd unit for droplet
  deployment.
- `scripts/` — one-off helpers (Finviz column discovery, alert review,
  baseline recovery).
- `tests/` — unit tests, run against synthetic data (no live credentials
  needed).
