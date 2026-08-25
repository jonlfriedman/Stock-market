# Premarket Volume Acceleration Scanner

Detects stocks whose premarket volume breaks out and *keeps building*
right around the 7:00 AM broker-unlock time, distinguishing real
ticker-specific moves from the market-wide volume step-up that happens
when retail platforms open trading access. Runs a strict two-phase
baseline/breakout/confirmation check every minute and texts a minimal SMS
via Twilio when a move confirms.

## How it works

```
Universe screen (Finviz Elite, once before BASELINE_START_TIME)
        |
        v
Fixed ticker list for the session, cached to disk
        |
        v
Phase 1 -- baseline window (06:45-07:00): poll every 1 min,
compute avg_vol_per_min per ticker over the window
        |
        v
Phase 2 -- trigger window (07:00 onward): poll every 1 min
  Trigger 1 (breakout): this minute's volume > avg_vol_per_min x multiplier
  Trigger 2 (confirmation): next 3 minutes stay elevated OR keep increasing
        |
        v
Confirmed --> Twilio SMS (ticker + price only) + logged to SQLite
Every poll (confirmed or not) --> data/logs/scan_YYYY-MM-DD.csv
        |
        v
Effectiveness tracking: price snapshots every 15 min after each
confirmed trigger, until 10:00 AM -- separate from alerting, for
retrospective "did this actually predict anything" analysis
```

RVOL (relative volume) is deliberately **not** used anywhere in the
trigger logic -- it's a lagging ratio against a historical average, not a
live rate-of-change signal, and updates too late to catch the "still
building" moment this system targets. Finviz's own RVOL/unusual-volume
screener already does a static-threshold version of this; it's not the
differentiator here.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

### 1. Finviz Elite

Get your personal Export API auth token from elite.finviz.com -> API ->
Screener Export, and set it as `FINVIZ_API_KEY` in `.env`. Treat it like a
password: `.env` is gitignored and the token must never be pasted into
chat, committed, or shared. The scanner builds two different URLs from
that key (see `premarket_scanner/finviz_client.py`):

1. **Universe screen** (`build_universe_url`) -- run once each morning
   before `BASELINE_START_TIME`, using `FINVIZ_UNIVERSE_FILTER` (default
   is the confirmed working filter from the build spec: PFCF under 20,
   common stocks only -- excludes SPACs/ETFs/funds, average volume over
   300K, price $1-$10). This defines the fixed ticker list for the whole
   session; it's cached to `data/universe/` so a restart mid-morning
   doesn't redraw a different list partway through.
2. **Live volume polling** (`build_quote_url`) -- every minute from
   `BASELINE_START_TIME` through `SCAN_END_TIME`, against exactly that
   fixed ticker list (`t=...`), no filters. This is what the baseline and
   triggers are computed from.

Column IDs for Finviz's export API aren't officially documented. Run the
header discovery helper once to confirm the actual CSV headers match the
defaults in `config.FieldMap`:

```bash
.venv/bin/python scripts/discover_finviz_columns.py
```

If any of Ticker/Price/Volume/Change differ, set the matching
`FINVIZ_FIELD_*` var in `.env`.

### 2. Twilio

Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, and
`TWILIO_TO_NUMBERS` (comma-separated for multiple recipients) in `.env`.
Leave `LIVE_ALERTING_ENABLED=false` until the diagnostic week is done --
see below. This is separate from `DRY_RUN`, which is just a manual
override for one-off test runs.

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

All tests run against synthetic data -- no Finviz or Twilio credentials
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

The service only actively polls within `UNIVERSE_FETCH_TIME`-`SCAN_END_TIME`
(weekdays); outside that window it sleeps until the next window, so it's
safe to leave running continuously.

## Diagnostic-first rollout (required before live alerting)

`LIVE_ALERTING_ENABLED` defaults to `false`. Run the full pipeline in this
log-only mode for approximately one week before turning it on. Every poll
(every ticker, every minute) is logged to `data/logs/scan_YYYY-MM-DD.csv`
regardless of whether it crosses a trigger, specifically so this week can
answer:

1. Does most/all of the universe see a volume jump right at 7:00 AM (the
   market-wide broker-unlock effect), or only some tickers?
2. If a market-wide effect exists, roughly how large is it on average?
   This becomes a normalization factor for judging individual tickers.
3. Which tickers still stand out after accounting for that effect --
   these inform real `TRIGGER_MULTIPLIER` tuning.

```bash
.venv/bin/python scripts/diagnostic_report.py
```

reports the cross-sectional median/mean `ratio_to_baseline` in the first
few minutes of the trigger window (a rough measure of the market-wide
step-up) and flags tickers whose ratio is well above that median (real
candidates). Only after this analysis should `TRIGGER_MULTIPLIER` be
tuned and `LIVE_ALERTING_ENABLED` flipped to `true`.

## Alert payload

Kept deliberately minimal per the build spec: `TICKER $PRICE`, nothing
else -- no scores, ratios, or extra metrics. Price % change is used only
as a secondary confirmation signal internally (visible in the CSV log),
never in the SMS text.

## Effectiveness tracking

Independent of what the SMS contains: for every confirmed trigger, price
is snapshotted every `EFFECTIVENESS_SNAPSHOT_MINUTES` (default 15) after
the trigger, continuing until `SCAN_END_TIME` (default 10:00 AM --
deliberately past the 9:30 AM open, since some moves only materialize
once regular-hours volume kicks in). Stored in the `effectiveness_snapshots`
SQLite table for retrospective analysis (e.g. "average % price move
15/30/45/60+ min after a trigger"), separate from any single trade
decision.

## Tuning

- `TRIGGER_MULTIPLIER`: starting point only (3.0x baseline avg
  volume/min). Set from the diagnostic week's `diagnostic_report.py`
  output.
- `CONFIRMATION_MINUTES`: how many minutes Trigger 2 watches after a
  breakout. Confirmation passes if volume stays at/above the breakout
  level for the whole window, OR keeps (non-strictly) increasing across
  it -- either is enough; both together aren't required.
- `ALERT_COOLDOWN_MINUTES`: minimum gap between SMS for the same ticker
  while a move keeps reconfirming.

## Profiles

- **Discovery** (default): the Finviz universe screen -- unfamiliar/
  small-cap names included, wider net. Configured via
  `FINVIZ_UNIVERSE_FILTER`.
- **Watchlist** (future refinement, not part of the initial build): your
  existing large-cap holdings. Set `SCANNER_PROFILE=watchlist` and
  `FINVIZ_WATCHLIST_TICKERS` to bypass the screener with an explicit
  ticker list. Add only after the Discovery profile's diagnostic rollout
  confirms the core trigger logic works. Run a second instance (separate
  systemd unit + `.env`, distinct `DATA_DIR`) to run both profiles at
  once.

## Known limitations (by design, not bugs)

- Premarket liquidity is thin; a volume spike can be a couple of orders,
  not real depth. Wide bid-ask spreads are a real execution risk on
  unfamiliar names -- verify manually before acting on any alert.
- Premarket data coverage for obscure microcaps may be incomplete even on
  Finviz Elite; watch for tickers with sparse or missing readings in the
  scan log.
- This is a screening/alerting edge, not a guaranteed early-mover
  advantage -- institutional/HFT systems already operate on this signal
  at much higher speed. No entry/exit rules, position sizing, or buy/sell
  logic are included or in scope. Validate via paper trading before using
  with live capital.
