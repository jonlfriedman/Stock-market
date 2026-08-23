# Premarket Volume Acceleration Scanner

Polls Finviz Elite starting at 4:00 AM ET, tracks per-ticker volume/price in
a rolling buffer, scores tickers on **sustained** volume acceleration (not
just a static relative-volume threshold), and pushes alerts via Pushover
when the score crosses a threshold — all before the 7:00 AM trading window.

## How it works

```
Finviz Elite export (CSV, every 60s)
        |
        v
RollingBuffer  --- last ~15 min of (timestamp, cumulative_volume, price) per ticker
        |
        v
Acceleration gate: 3 consecutive window ratios (W1->W2->W3->W4), only
"sustained" if ratios are non-decreasing or all > 1.0 (rejects single spikes)
        |
        v
RVOL: current volume vs. same time-of-day average over the last 20 trading
days. Falls back to Finviz's own "Relative Volume" column until the scanner has
collected enough of its own history (RVOL_MIN_HISTORY_DAYS, default 10 days)
        |
        v
Score = accel * 0.6 + rvol * 0.25 + |price % change| * 0.15
        |
        v
Score >= threshold and cooldown elapsed --> Pushover push + logged to SQLite
Every scored row (alerted or not) --> data/logs/scores_YYYY-MM-DD.csv
```

The CSV log of every poll (not just alerts) is deliberate: Phase 1 is meant
to over-alert and gather data, then tighten `SCORE_THRESHOLD` and friends
using what actually happened, per the build spec.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

### 1. Get a Finviz Elite export URL

On elite.finviz.com, go to your account menu (top-right) -> **API** ->
**Screener** tab. That page documents the whole flow and shows your live
auth token:

1. **Configure Screener** — build your filters in the normal Screener UI:
   **Average Volume** "Over 300K" (`sh_avgvol_o300`), **Relative Volume**
   "Over 1.5" (`sh_relvol_o1.5`). Use Average Volume, not Current Volume —
   Current Volume is today's volume-so-far, which is near-zero for most
   tickers early in the premarket session and would filter out exactly the
   stocks this scanner is trying to catch.
2. **Replace URL path**: change `/screener` to `/export/screener` (same
   query string).
3. **Customize columns** (optional but recommended): append
   `&c=1,65,66,67,64,63` to pin the exact columns
   (Ticker, Price, Change, Volume, Relative Volume, Average Volume) instead
   of relying on whatever the screener view happens to show by default.
4. **Add authentication**: append `&auth=<your-token>` — the token shown on
   that same API page.

Result looks like:

```
https://elite.finviz.com/export/screener?v=111&f=sh_avgvol_o300,sh_relvol_o1.5&c=1,65,66,67,64,63&auth=<your-token>
```

Paste it into `.env` as `FINVIZ_EXPORT_URL_DISCOVERY`.

Treat that token like a password: it's tied to your Elite account and goes
in `.env` only (gitignored, never committed). If it's ever pasted somewhere
shared — a screenshot, a chat, a public repo — regenerate it from that same
API page ("Regenerate Token").

Finviz's export API doesn't have separate premarket-specific columns (no
"Pre-Market Price/Volume" fields exist in their documented column list) —
the standard Price/Change/Volume columns already carry live premarket data
during the scan window, so no extra column mapping is needed for that.

As a final sanity check, run the header discovery helper once against your
real URL:

```bash
.venv/bin/python scripts/discover_finviz_columns.py
```

This prints the actual CSV column headers your export produces. If any of
Ticker/Price/Volume/Change/Relative Volume differ from the defaults, set
the matching `FINVIZ_FIELD_*` var in `.env` to the exact header text shown.

### 2. Pushover

1. Install the Pushover app (iOS/Android) and create an account.
2. On pushover.net, create an Application/API Token (any name, e.g.
   "Premarket Scanner") — this gives you `PUSHOVER_API_TOKEN`.
3. Your `PUSHOVER_USER_KEY` is shown on your account's main page after login.
4. Set both in `.env`. Leave `DRY_RUN=true` while testing — alerts are
   logged instead of sent.

Pushover was chosen over SMS/Twilio for this project specifically because it
needs no telco sender registration (Twilio SMS requires A2P 10DLC/toll-free
verification, which is real friction to set up from a phone) — just the app
plus a token and user key.

### 3. Run

```bash
# Single poll cycle, no loop, for testing:
.venv/bin/python -m premarket_scanner --once --dry-run --verbose

# Continuous (intended to run under systemd, see deploy/):
.venv/bin/python -m premarket_scanner
```

### 4. Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

All tests run against synthetic data — no Finviz or Pushover credentials
needed.

## Deployment (small droplet)

```bash
# On the droplet, as root:
useradd -r -s /bin/false scanner
mkdir -p /opt/premarket-scanner
# copy the repo + your real .env into /opt/premarket-scanner
cd /opt/premarket-scanner
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
chown -R scanner:scanner /opt/premarket-scanner

cp deploy/premarket-scanner.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now premarket-scanner
journalctl -u premarket-scanner -f
```

The service only actively polls within `SCAN_START_TIME`–`SCAN_END_TIME`
(weekdays); outside that window it sleeps until the next window, so it's
safe to leave running continuously.

## Tuning (Phase 1 -> Phase 2)

Start loose (`SCORE_THRESHOLD=3.0` in `.env.example` is a starting point,
not a validated number). After a week, pull `data/logs/scores_*.csv` and:

- Check what score range actual movers hit vs. noise, and raise
  `SCORE_THRESHOLD` accordingly.
- If real moves are getting missed by the acceleration gate, loosen the
  "non-decreasing ratios" requirement (already accepts "all ratios > 1.0"
  as an alternate pass condition — see `scoring.compute_acceleration`).
- `RVOL_MIN_HISTORY_DAYS` controls when the scanner switches from Finviz's
  static Relative Volume to its own time-of-day baseline (`rvol_source` column
  in the log shows which was used for each row).

## Reviewing whether alerts actually worked

Every alert records the price at the moment it fired. Afterward, the
scanner automatically looks back and fills in what the price did 15, 30,
and 60 minutes later (`Storage.backfill_alert_outcomes`, called once per
poll cycle) -- so each alert ends up with its own before/after result, not
just a point-in-time score.

To review them:

```bash
.venv/bin/python scripts/review_alerts.py
```

This prints every alert with its score, acceleration/RVOL, and the price
change at each horizon (blank = not enough time has passed yet to fill it
in). This is the actual evidence for the Phase-1 "run a week, then
reassess" review -- whether "sustained acceleration" alerts saw real
follow-through, not just a one-time RVOL spike.

## Profiles

- **Discovery** (default): wide net over Finviz's RVOL-filtered screener —
  unfamiliar/small-cap names included. Configured via
  `FINVIZ_EXPORT_URL_DISCOVERY`.
- **Watchlist**: intended for your existing large-cap holdings with tighter
  liquidity requirements. Wired into config (`FINVIZ_EXPORT_URL_WATCHLIST`,
  `--profile watchlist`) but not yet populated with a real export URL — add
  one once the Discovery profile has been validated, per the build spec.
  Run a second instance of the service (separate systemd unit + `.env`, or
  `SCANNER_PROFILE=watchlist` and a distinct `DATA_DIR`) to run both at once.

## Known limitations (by design, not bugs)

- Premarket liquidity is thin; a volume spike can be a couple of orders,
  not real depth. Verify manually before acting on any alert.
- RVOL is Finviz's static ratio until the scanner has ~10+ trading days of
  its own history — early alerts are less precise on that dimension.
- This is a screening/alerting tool, not a trading system: no entry/exit
  rules, position sizing, or buy/sell logic are included or in scope.
  Validate via paper trading before using with live capital.
