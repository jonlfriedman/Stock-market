# Premarket Volume Acceleration Scanner

Polls Finviz Elite starting at 4:00 AM ET, tracks per-ticker volume/price in
a rolling buffer, scores tickers on **sustained** volume acceleration (not
just a static relative-volume threshold), and texts alerts via Twilio when
the score crosses a threshold — all before the 7:00 AM trading window.

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
days. Falls back to Finviz's own "Rel Volume" column until the scanner has
collected enough of its own history (RVOL_MIN_HISTORY_DAYS, default 10 days)
        |
        v
Score = accel * 0.6 + rvol * 0.25 + |price % change| * 0.15
        |
        v
Score >= threshold and cooldown elapsed --> Twilio SMS + logged to SQLite
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

Finviz's export column IDs aren't officially documented, so rather than
constructing the request from scratch:

1. In the Finviz Elite screener UI, set filters: **Relative Volume** "Over
   1.5" (or 2), **Average Volume** "Over 300K".
2. Click **Export**. Copy the resulting `export.ashx?...` URL — it already
   carries your auth token, view, and filters.
3. Paste it into `.env` as `FINVIZ_EXPORT_URL_DISCOVERY`.

Then run the header discovery helper once:

```bash
.venv/bin/python scripts/discover_finviz_columns.py
```

This prints the actual CSV column headers your export produces. If any of
Ticker/Price/Volume/Change/Rel Volume differ from the defaults (this is
likely for premarket-specific columns), set the matching `FINVIZ_FIELD_*`
var in `.env` to the exact header text shown.

### 2. Twilio

Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, and
`TWILIO_TO_NUMBERS` (comma-separated for multiple recipients) in `.env`.
Leave `DRY_RUN=true` while testing — alerts are logged instead of sent.

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

All tests run against synthetic data — no Finviz or Twilio credentials
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
  static Rel Volume to its own time-of-day baseline (`rvol_source` column
  in the log shows which was used for each row).

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
