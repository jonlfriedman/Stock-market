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

Known as of 2026-08-30:
- Droplet IP: `157.230.1.250`
- Expected deploy path per `deploy/premarket-scanner.service`:
  `/opt/premarket-scanner`, running as systemd unit `premarket-scanner`,
  under a `scanner` user.
- Which branch/commit is actually deployed there is **unconfirmed** — the
  repo has multiple divergent, unmerged branches (see below), and nobody
  has recorded which one (if any) was pushed to the droplet.
- Whether the service has actually been enabled/running, and for how
  long, is **unconfirmed** — needs to be checked on the droplet itself.
- The scanner's `data/` directory (logs, SQLite alert history, score
  CSVs) is gitignored by design (keeps credentials/data out of git). That
  means any collected data exists **only on the droplet's disk**, at
  `/opt/premarket-scanner/data` if deployed per the README — it will
  never show up by looking at this git repo alone.

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
