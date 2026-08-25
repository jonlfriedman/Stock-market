# Premarket Volume Acceleration Scanner

Polls Finviz Elite starting at 4:00 AM ET, tracks per-ticker volume/price in
a rolling buffer, scores tickers on **sustained** volume acceleration with
flat-or-up price confirmation, and pushes alerts via Pushover when the score
crosses a threshold — all before the 7:00 AM trading window.

## How it works

```
Finviz Elite export (CSV, every 60s) -- screener does the static filtering
(price range, profitability, exclude funds, average-volume liquidity floor);
deliberately no Relative Volume filter here, see below
        |
        v
RollingBuffer  --- last ~15 min of (timestamp, cumulative_volume, price) per ticker
        |
        v
Acceleration gate: 3 consecutive window ratios (W1->W2->W3->W4), only
"sustained" if ratios are non-decreasing or all > 1.0 (rejects single spikes)
        |
        v
Price-direction gate: discard if price_change_pct < MIN_PRICE_CHANGE_PCT
(default 0.0) -- accelerating volume on a stock trending DOWN is discarded,
only flat-or-up price action confirms the move is worth scoring
        |
        v
Score = accel * 0.8 + price % change * 0.2
        |
        v
Score >= threshold and cooldown elapsed --> Pushover push + logged to SQLite
Every scored row (alerted or not) --> data/logs/scores_YYYY-MM-DD.csv
```

**Why no Relative Volume filter or scoring weight:** it was originally both
a Finviz screener pre-filter and 25% of the score, but two problems showed
up against live trading data. First, Finviz's own RVOL snapshot isn't
time-of-day adjusted -- it's roughly (volume so far today) / (a typical
full day's volume), so it mechanically climbs through the morning
regardless of whether anything unusual is actually happening, which biased
alerts toward firing too late to act on. Second, illiquid microcaps can
show 20x-40x+ RVOL on one erratic historical baseline, which (even capped)
still added noise unrelated to real acceleration. RVOL is still computed
and logged (`rvol`/`rvol_source` columns in the CSV, and shown in the alert
message) for context, just no longer part of the score or the Finviz
pre-filter -- the scanner's own per-minute acceleration tracking is what
decides what counts as "unusual" now.

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

1. **Configure Screener** — build your filters in the normal Screener UI.
   **Average Volume** "Over 300K" (`sh_avgvol_o300`) for liquidity — use
   Average Volume, not Current Volume; Current Volume is today's
   volume-so-far, which is near-zero for most tickers early in the
   premarket session and would filter out exactly the stocks this scanner
   is trying to catch. Add price range, profitability, and exclude-funds
   filters as desired (build these in the live UI and check the resulting
   `f=` filter codes rather than guessing — they're easy to get subtly
   wrong). Deliberately **no Relative Volume filter** — see "Why no
   Relative Volume filter" above for why that biased alerts toward firing
   too late.
2. **Replace URL path**: change `/screener` to `/export/screener` (same
   query string).
3. **Customize columns**: append `&c=1,65,66,67,64,63` to pin the exact
   columns (Ticker, Price, Change, Volume, Relative Volume, Average Volume).
   This is *not* optional in practice: the default `v=111` ("Overview")
   screener view ignores `&c=` entirely and always returns its own fixed
   11-column layout (No./Ticker/Company/Sector/Industry/Country/Market
   Cap/P-E/Price/Change/Volume) -- which has no Relative Volume or Average
   Volume column at all, silently breaking RVOL scoring. Change `v=111` to
   **`v=152`** in the URL for `&c=` to actually take effect.
4. **Add authentication**: append `&auth=<your-token>` — the token shown on
   that same API page.

Result looks like:

```
https://elite.finviz.com/export/screener?v=152&f=sh_avgvol_o300,<your-other-filters>&c=1,65,66,67,64,63&auth=<your-token>
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
- `RVOL_MIN_HISTORY_DAYS` controls when the logged RVOL switches from
  Finviz's static Relative Volume to the scanner's own time-of-day baseline
  (`rvol_source` column in the log shows which was used for each row) —
  informational only now, doesn't affect scoring or alerts.
- `MIN_PRICE_CHANGE_PCT` (default 0.0) discards tickers trending down
  despite accelerating volume. Raise it above 0 to require a stronger
  confirming move, or lower it (negative) to allow a small pullback through.

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
