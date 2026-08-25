"""Two-phase baseline / breakout / confirmation trigger logic.

Phase 1 (baseline window, e.g. 6:45-7:00): record_baseline_reading() for
each per-minute poll, then finalize_baseline() once at the start of Phase 2
to compute each ticker's avg_vol_per_min.

Phase 2 (trigger window, 7:00 onward): evaluate() each minute.

  Trigger 1 (breakout): this minute's volume > avg_vol_per_min * multiplier.
  Trigger 2 (confirmation): watch the next `confirmation_minutes` minutes;
    confirmed if volume stays at/above the breakout level for all of them,
    OR keeps increasing (non-decreasing) across them. Either condition
    passes -- this rejects a single spike that immediately fades, while
    still accepting sustained-but-not-strictly-increasing volume.

Deliberately NOT using RVOL (a lagging historical ratio) -- this reacts to
this session's own live rate of change, per the build spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def check_confirmation(watch_deltas: list[float], breakout_level: float) -> bool:
    if not watch_deltas:
        return False
    stays_elevated = all(d >= breakout_level for d in watch_deltas)
    keeps_increasing = all(watch_deltas[i] >= watch_deltas[i - 1] for i in range(1, len(watch_deltas)))
    return stays_elevated or keeps_increasing


@dataclass
class _TickerState:
    last_cum_volume: float | None = None
    baseline_deltas: list[float] = field(default_factory=list)
    baseline_avg: float | None = None
    watching: bool = False
    watch_deltas: list[float] = field(default_factory=list)
    trigger1_time: datetime | None = None


@dataclass
class TriggerReading:
    ticker: str
    timestamp: datetime
    minute_volume: float | None
    baseline_avg: float | None
    ratio_to_baseline: float | None
    trigger1_fired: bool
    trigger2_confirmed: bool
    watching: bool


class TriggerEngine:
    def __init__(self, multiplier: float, confirmation_minutes: int):
        self.multiplier = multiplier
        self.confirmation_minutes = max(1, confirmation_minutes)
        self._states: dict[str, _TickerState] = {}

    def _state(self, ticker: str) -> _TickerState:
        return self._states.setdefault(ticker, _TickerState())

    def _minute_delta(self, state: _TickerState, cum_volume: float) -> float | None:
        delta = None
        if state.last_cum_volume is not None:
            delta = max(0.0, cum_volume - state.last_cum_volume)
        state.last_cum_volume = cum_volume
        return delta

    def record_baseline_reading(self, ticker: str, cum_volume: float) -> None:
        state = self._state(ticker)
        delta = self._minute_delta(state, cum_volume)
        if delta is not None:
            state.baseline_deltas.append(delta)

    def finalize_baseline(self) -> dict[str, float | None]:
        result: dict[str, float | None] = {}
        for ticker, state in self._states.items():
            state.baseline_avg = (
                sum(state.baseline_deltas) / len(state.baseline_deltas) if state.baseline_deltas else None
            )
            result[ticker] = state.baseline_avg
        return result

    def evaluate(self, ticker: str, timestamp: datetime, cum_volume: float) -> TriggerReading:
        state = self._state(ticker)
        delta = self._minute_delta(state, cum_volume)
        baseline_avg = state.baseline_avg

        if delta is None or not baseline_avg or baseline_avg <= 0:
            return TriggerReading(ticker, timestamp, delta, baseline_avg, None, False, False, state.watching)

        ratio = delta / baseline_avg
        breakout_level = baseline_avg * self.multiplier
        trigger1 = False
        trigger2 = False

        if state.watching:
            state.watch_deltas.append(delta)
            if len(state.watch_deltas) >= self.confirmation_minutes:
                trigger2 = check_confirmation(state.watch_deltas, breakout_level)
                state.watching = False
                state.watch_deltas = []
                state.trigger1_time = None
        elif delta > breakout_level:
            trigger1 = True
            state.watching = True
            state.watch_deltas = []
            state.trigger1_time = timestamp

        return TriggerReading(ticker, timestamp, delta, baseline_avg, ratio, trigger1, trigger2, state.watching)

    def known_tickers(self) -> list[str]:
        return list(self._states.keys())
