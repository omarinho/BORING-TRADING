"""Pure OHLCV-based setup detection for Setup 1 (breakout) and Setup 2 (pullback).

Every function here takes bar data in and returns a decision — no I/O, no ib_insync import,
no network/file access anywhere in this module (REQ-002).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as _date

from korkoban import config

# The pullback volume comparison ratio isn't one of the tunable thresholds already defined
# in config.py (out of scope to edit here), so the interpretation is documented locally.
PULLBACK_VOLUME_RATIO_MAX: float = 0.8


@dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Setup1Signal:
    direction: str
    entry_price: float
    atr14: float
    date: str


@dataclass(frozen=True)
class Setup2Signal:
    direction: str
    entry_price: float
    atr14: float


def _true_range(current: Bar, previous_close: float) -> float:
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )


def _atr_series(bars: list[Bar], period: int) -> list[float]:
    # atr_series[k] is the trailing `period`-day average true range ending at bars[k+period].
    true_ranges = [_true_range(bars[i], bars[i - 1].close) for i in range(1, len(bars))]
    return [
        sum(true_ranges[end - period : end]) / period for end in range(period, len(true_ranges) + 1)
    ]


def _sma(values: list[float], period: int) -> float:
    return sum(values[-period:]) / period


def _percentile_nearest_rank(values: list[float], pct: float) -> float:
    # Nearest-rank method: deterministic, unambiguous at exact percentile boundaries.
    ordered = sorted(values)
    rank = math.ceil((pct / 100.0) * len(ordered))
    index = max(0, min(len(ordered) - 1, rank - 1))
    return ordered[index]


def is_breakout(bars: list[Bar]) -> Setup1Signal | None:
    min_required = config.ATR_PERIOD + config.ATR_PERCENTILE_WINDOW_DAYS + 1
    if len(bars) < min_required:
        # A short history can't support a real 252-day ATR percentile; raise instead of
        # silently comparing against an undersized/skewed distribution.
        raise ValueError(f"is_breakout requires at least {min_required} bars, got {len(bars)}")

    current = bars[-1]

    # Condition 1: close breaks beyond the prior N-day high/low (current bar excluded).
    lookback_window = bars[-(config.BREAKOUT_LOOKBACK_DAYS + 1) : -1]
    prior_high = max(bar.high for bar in lookback_window)
    prior_low = min(bar.low for bar in lookback_window)
    if current.close > prior_high:
        direction = "long"
    elif current.close < prior_low:
        direction = "short"
    else:
        return None

    # Condition 2: current volume vs. the trailing average (current bar excluded so a
    # single day's spike can't inflate its own baseline).
    volume_window = bars[-(config.AVG_VOLUME_LOOKBACK_DAYS + 1) : -1]
    avg_volume = sum(bar.volume for bar in volume_window) / len(volume_window)
    if current.volume < config.VOLUME_RATIO_MULTIPLE * avg_volume:
        return None

    # Condition 3: 100d SMA slope, measured strictly before today (excludes the current
    # bar entirely) so the breakout candle itself can't tilt its own trend confirmation.
    # Reuses BREAKOUT_LOOKBACK_DAYS as the slope-comparison gap rather than adding a new constant.
    closes = [bar.close for bar in bars]
    sma_recent = _sma(closes[:-1], config.TREND_MA_LOOKBACK_DAYS)
    gap = config.BREAKOUT_LOOKBACK_DAYS
    sma_prior = _sma(closes[: -1 - gap], config.TREND_MA_LOOKBACK_DAYS)
    slope = sma_recent - sma_prior
    if direction == "long" and slope <= 0:
        return None
    if direction == "short" and slope >= 0:
        return None

    # Condition 4: ATR14 strictly below the 90th percentile of the trailing 252 days
    # (current bar excluded from the historical distribution it's compared against).
    atr_series = _atr_series(bars, config.ATR_PERIOD)
    historical_atr = atr_series[-(config.ATR_PERCENTILE_WINDOW_DAYS + 1) : -1]
    current_atr = atr_series[-1]
    cutoff = _percentile_nearest_rank(historical_atr, config.ATR_PERCENTILE_CUTOFF)
    if not current_atr < cutoff:
        return None

    return Setup1Signal(
        direction=direction, entry_price=current.close, atr14=current_atr, date=current.date
    )


def is_pullback(bars: list[Bar], prior_breakout: Setup1Signal | None) -> Setup2Signal | None:
    if prior_breakout is None:
        return None

    direction = prior_breakout.direction
    current = bars[-1]

    # A breakout older than PULLBACK_BREAKOUT_MAX_AGE_DAYS no longer pairs with a fresh
    # signal — otherwise a single old breakout can keep re-triggering indefinitely off swing
    # highs/lows made long after its own impulse.
    age_days = (_date.fromisoformat(current.date) - _date.fromisoformat(prior_breakout.date)).days
    if age_days > config.PULLBACK_BREAKOUT_MAX_AGE_DAYS:
        return None

    # Scoped to bars from the breakout day forward: searching the full history would let an
    # old breakout keep pairing with "pullback" signals off swing highs/lows made long after
    # its own impulse, rather than a retracement of that impulse.
    bars_since_breakout = [bar for bar in bars if bar.date >= prior_breakout.date]

    if direction == "long":
        extreme = max(bar.high for bar in bars_since_breakout)
        extreme_bar = max(bars_since_breakout, key=lambda bar: bar.high)
        impulse_size = extreme - prior_breakout.entry_price
        if impulse_size <= 0:
            return None
        retracement_pct = (extreme - current.close) / impulse_size
    else:
        extreme = min(bar.low for bar in bars_since_breakout)
        extreme_bar = min(bars_since_breakout, key=lambda bar: bar.low)
        impulse_size = prior_breakout.entry_price - extreme
        if impulse_size <= 0:
            return None
        retracement_pct = (current.close - extreme) / impulse_size

    if not config.RETRACEMENT_MIN_PCT <= retracement_pct <= config.RETRACEMENT_MAX_PCT:
        return None

    # "Clearly lower" pullback volume vs. the impulse-extreme bar's volume — 0.8x is a
    # documented interpretation call, not a value specified numerically in the requirements.
    if current.volume >= PULLBACK_VOLUME_RATIO_MAX * extreme_bar.volume:
        return None

    closes = [bar.close for bar in bars]
    ma = _sma(closes, config.PULLBACK_MA_LOOKBACK_DAYS)
    if direction == "long" and current.close < ma:
        return None
    if direction == "short" and current.close > ma:
        return None

    atr_period = min(config.ATR_PERIOD, len(bars) - 1)
    current_atr = _atr_series(bars, atr_period)[-1]
    return Setup2Signal(direction=direction, entry_price=current.close, atr14=current_atr)
