# REQ-002, REQ-003, REQ-004
"""Unit tests for korkoban.setups: Setup 1 (breakout) and Setup 2 (pullback) detection,
plus the structural audit that setups.py stays a pure function of OHLCV data (REQ-002).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from korkoban import config
from korkoban.setups import Bar, Setup1Signal, is_breakout, is_pullback

REPO_ROOT = Path(__file__).resolve().parents[2]
_START_DATE = date(2020, 1, 1)
_BASELINE_VOLUME = 100_000.0


def _dates(n: int) -> list[str]:
    return [(_START_DATE + timedelta(days=i)).isoformat() for i in range(n)]


def _bar(day: str, mid: float, tr: float, volume: float) -> Bar:
    return Bar(date=day, open=mid, high=mid + tr / 2, low=mid - tr / 2, close=mid, volume=volume)


# --- Setup 1 (breakout) synthetic-data plumbing ------------------------------------------
# Bar count chosen so the trailing ATR-percentile window (Condition 4) is always
# satisfiable: ATR_PERIOD (14) warm-up + ATR_PERCENTILE_WINDOW_DAYS (252) history + 1 current bar.
_BREAKOUT_BAR_COUNT = config.ATR_PERIOD + config.ATR_PERCENTILE_WINDOW_DAYS + 1  # 267
_HIGH_ATR_BLOCK_END = 39  # bars[1..39] get TR=5.0, the rest of history gets TR=1.0
_UPTREND_RATE = 0.002  # tiny daily drift, just enough to give the 100d SMA slope a clear sign
_BASE_PRICE = 1000.0
_JUMP = 2.0  # current-bar close offset used to clear the prior 20-day high/low


def _breakout_bars(
    *,
    direction: str = "long",
    trend_rate: float = _UPTREND_RATE,
    jump: float | None = _JUMP,
    current_volume_ratio: float = 2.0,
    current_tr: float = 1.0,
) -> list[Bar]:
    """Builds a bar series where, by default, all four Setup-1 conditions hold.

    History TR is piecewise-constant so trailing ATR is fully controllable: bars[1..39] use
    TR=5.0 (a past volatility block) and bars[40..-2] use TR=1.0 (a calm block). With
    ATR_PERIOD=14 this yields a clean, hand-verified trailing-252-day 90th-percentile ATR
    cutoff of exactly 5.0 (26 clean high-ATR days, 213 clean low-ATR days, 13 transition days
    land below the cutoff rank). The current bar's own TR is `current_tr`, so callers steer
    condition 4 independently of the rest of the history.
    """
    n = _BREAKOUT_BAR_COUNT
    sign = 1.0 if direction == "long" else -1.0
    dates = _dates(n)

    mids = [_BASE_PRICE + sign * trend_rate * i for i in range(n - 1)]
    last_mid = _BASE_PRICE + sign * trend_rate * (n - 1)
    if jump is not None:
        last_mid += sign * jump
    mids.append(last_mid)

    trs = [1.0] * n
    for i in range(1, _HIGH_ATR_BLOCK_END + 1):
        trs[i] = 5.0
    trs[-1] = current_tr

    volumes = [_BASELINE_VOLUME] * n
    volumes[-1] = current_volume_ratio * _BASELINE_VOLUME

    return [_bar(d, m, tr, v) for d, m, tr, v in zip(dates, mids, trs, volumes, strict=True)]


def test_long_breakout_all_conditions_true_returns_signal() -> None:
    # TC-002-01
    signal = is_breakout(_breakout_bars(direction="long"))
    assert signal is not None
    assert signal.direction == "long"


def test_short_breakout_all_conditions_true_returns_signal() -> None:
    # TC-002-02
    signal = is_breakout(_breakout_bars(direction="short"))
    assert signal is not None
    assert signal.direction == "short"


def test_breakout_fails_when_close_does_not_clear_prior_high() -> None:
    # TC-002-03
    bars = _breakout_bars(direction="long", jump=None)
    assert is_breakout(bars) is None


def test_breakout_fails_when_volume_just_below_multiple() -> None:
    # TC-002-04
    bars = _breakout_bars(direction="long", current_volume_ratio=1.79)
    assert is_breakout(bars) is None


def test_breakout_signal_when_volume_exactly_at_multiple_boundary() -> None:
    # TC-002-05
    bars = _breakout_bars(direction="long", current_volume_ratio=config.VOLUME_RATIO_MULTIPLE)
    assert is_breakout(bars) is not None


def test_breakout_fails_when_trend_slope_is_flat() -> None:
    # TC-002-06
    bars = _breakout_bars(direction="long", trend_rate=0.0)
    assert is_breakout(bars) is None


def test_breakout_fails_when_atr_exactly_at_90th_percentile() -> None:
    # TC-002-07 — current_tr=57.0 puts current ATR14 exactly at the 5.0 cutoff (excluded)
    bars = _breakout_bars(direction="long", current_tr=57.0)
    assert is_breakout(bars) is None


def test_breakout_signal_when_atr_just_below_90th_percentile() -> None:
    # TC-002-08 — current_tr=55.6 puts current ATR14 at 4.9, just below the 5.0 cutoff
    bars = _breakout_bars(direction="long", current_tr=55.6)
    assert is_breakout(bars) is not None


def test_breakout_raises_value_error_when_history_too_short() -> None:
    # TC-002-09 — fewer than the required trailing days: raise rather than silently
    # miscompute a percentile over an undersized/skewed distribution.
    bars = _breakout_bars(direction="long")[:100]
    with pytest.raises(ValueError):
        is_breakout(bars)


def test_no_signal_when_bars_match_neither_setup() -> None:
    # TC-004-01
    bars = _breakout_bars(direction="long", trend_rate=0.0, jump=None, current_volume_ratio=1.0)
    assert is_breakout(bars) is None
    assert is_pullback(bars, None) is None


def test_near_miss_breakout_with_one_condition_false_returns_none() -> None:
    # TC-004-02 — breakout, volume, and trend all hold; only the ATR-percentile condition fails
    bars = _breakout_bars(direction="long", current_tr=57.0)
    assert is_breakout(bars) is None


def test_setups_module_has_no_io_or_broker_imports() -> None:
    # Architecture rule: setups.py must be a pure function of OHLCV data, no I/O anywhere.
    source = (REPO_ROOT / "korkoban" / "setups.py").read_text(encoding="utf-8")
    assert "import ib_insync" not in source
    assert "open(" not in source


# --- Setup 2 (pullback) synthetic-data plumbing ------------------------------------------
_PULLBACK_ENTRY_PRICE = 1000.0
_PULLBACK_EXTREME = 1050.0  # impulsive-move high reached before the pullback begins
_IMPULSE_VOLUME = 500_000.0
_PULLBACK_VOLUME_LOW = 100_000.0  # well under 0.8x impulse volume -> "clearly lower"
_BASE_BAR_COUNT = 40


def _pullback_bars(
    retracement_pct: float,
    *,
    pullback_volume: float = _PULLBACK_VOLUME_LOW,
    base_low: float = 950.0,
    base_high: float = 1000.0,
) -> list[Bar]:
    """Rising base phase (anchors the 20d MA) + one impulse bar to the extreme + a short,
    lower-volume pullback that retraces toward the requested percentage of the impulsive move.
    """
    pullback_days = 5
    dates = _dates(_BASE_BAR_COUNT + 1 + pullback_days)
    bars: list[Bar] = []

    for i in range(_BASE_BAR_COUNT):
        mid = base_low + (base_high - base_low) * i / (_BASE_BAR_COUNT - 1)
        bars.append(_bar(dates[i], mid, 1.0, _BASELINE_VOLUME))

    bars.append(_bar(dates[_BASE_BAR_COUNT], 1045.0, 10.0, _IMPULSE_VOLUME))

    target_close = _PULLBACK_EXTREME - retracement_pct * (_PULLBACK_EXTREME - _PULLBACK_ENTRY_PRICE)
    pullback_start = 1044.0
    for step in range(1, pullback_days + 1):
        mid = pullback_start + (target_close - pullback_start) * step / pullback_days
        idx = _BASE_BAR_COUNT + step
        bars.append(_bar(dates[idx], mid, 1.0, pullback_volume))

    return bars


def _pullback_prior_breakout() -> Setup1Signal:
    return Setup1Signal(direction="long", entry_price=_PULLBACK_ENTRY_PRICE, atr14=1.0)


def test_valid_pullback_within_retracement_band_returns_signal() -> None:
    # TC-003-01 — 44% retrace, clearly-lower volume, MA respected
    signal = is_pullback(_pullback_bars(0.44), _pullback_prior_breakout())
    assert signal is not None
    assert signal.direction == "long"


def test_pullback_with_no_prior_breakout_returns_none() -> None:
    # TC-003-02
    assert is_pullback(_pullback_bars(0.44), None) is None


def test_pullback_below_retracement_band_returns_none() -> None:
    # TC-003-03 — 37% retrace
    assert is_pullback(_pullback_bars(0.37), _pullback_prior_breakout()) is None


def test_pullback_at_retracement_min_boundary_returns_signal() -> None:
    # TC-003-04 — 38% boundary, inclusive
    bars = _pullback_bars(config.RETRACEMENT_MIN_PCT)
    assert is_pullback(bars, _pullback_prior_breakout()) is not None


def test_pullback_at_retracement_max_boundary_returns_signal() -> None:
    # TC-003-05 — 50% boundary, inclusive
    bars = _pullback_bars(config.RETRACEMENT_MAX_PCT)
    assert is_pullback(bars, _pullback_prior_breakout()) is not None


def test_pullback_above_retracement_band_returns_none() -> None:
    # TC-003-06 — 51% retrace
    assert is_pullback(_pullback_bars(0.51), _pullback_prior_breakout()) is None


def test_pullback_fails_when_volume_not_clearly_lower() -> None:
    # TC-003-07 — pullback volume at 0.9x impulse volume, not clearly lower
    bars = _pullback_bars(0.44, pullback_volume=0.9 * _IMPULSE_VOLUME)
    assert is_pullback(bars, _pullback_prior_breakout()) is None


def test_pullback_fails_when_close_through_ma_against_trend() -> None:
    # TC-003-08 — base phase raised near the peak so the 20d MA sits above the pullback close
    bars = _pullback_bars(0.44, base_low=1030.0, base_high=1040.0)
    assert is_pullback(bars, _pullback_prior_breakout()) is None
