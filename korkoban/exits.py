"""Exit math: where the stop, target, and time-boundary sit for an open position.

A stop is computed once at entry and never widened or recomputed afterward — there is
deliberately no function here that takes an existing stop and returns a new one.
"""

from __future__ import annotations

from dataclasses import dataclass

from korkoban import config

_LONG = "long"
_SHORT = "short"


@dataclass(frozen=True)
class ManagementPlan:
    scale_out_fraction: float
    scale_out_r_multiple: float
    trail_atr_multiple: float


def compute_initial_stop(
    entry_price: float,
    atr14: float,
    direction: str,
    stop_atr_multiple: float = config.STOP_ATR_MULTIPLE_DEFAULT,
) -> float:
    if not (config.STOP_ATR_MULTIPLE_MIN <= stop_atr_multiple <= config.STOP_ATR_MULTIPLE_MAX):
        raise ValueError(
            f"stop_atr_multiple {stop_atr_multiple} outside bounds "
            f"[{config.STOP_ATR_MULTIPLE_MIN}, {config.STOP_ATR_MULTIPLE_MAX}]"
        )
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be one of {{'long', 'short'}}, got {direction!r}")

    if direction == _LONG:
        return entry_price - stop_atr_multiple * atr14
    return entry_price + stop_atr_multiple * atr14


def compute_target(
    entry_price: float,
    initial_stop: float,
    direction: str,
    target_r_multiple: float = config.TARGET_R_MULTIPLE_DEFAULT,
) -> float:
    if not (config.TARGET_R_MULTIPLE_MIN <= target_r_multiple <= config.TARGET_R_MULTIPLE_MAX):
        raise ValueError(
            f"target_r_multiple {target_r_multiple} outside bounds "
            f"[{config.TARGET_R_MULTIPLE_MIN}, {config.TARGET_R_MULTIPLE_MAX}]"
        )
    if direction not in (_LONG, _SHORT):
        raise ValueError(f"direction must be one of {{'long', 'short'}}, got {direction!r}")

    initial_risk = abs(entry_price - initial_stop)
    if direction == _LONG:
        return entry_price + target_r_multiple * initial_risk
    return entry_price - target_r_multiple * initial_risk


def compute_management_plan(
    scale_out_r_multiple: float = config.SCALE_OUT_R_MULTIPLE,
    scale_out_fraction: float = config.SCALE_OUT_FRACTION,
    trail_atr_multiple: float = config.TRAIL_ATR_MULTIPLE,
) -> ManagementPlan:
    return ManagementPlan(
        scale_out_fraction=scale_out_fraction,
        scale_out_r_multiple=scale_out_r_multiple,
        trail_atr_multiple=trail_atr_multiple,
    )


def check_time_stop(
    bars_since_entry: int,
    realized_r: float,
    time_stop_bars: int = config.TIME_STOP_BARS_DEFAULT,
) -> bool:
    if not (config.TIME_STOP_BARS_MIN <= time_stop_bars <= config.TIME_STOP_BARS_MAX):
        raise ValueError(
            f"time_stop_bars {time_stop_bars} outside bounds "
            f"[{config.TIME_STOP_BARS_MIN}, {config.TIME_STOP_BARS_MAX}]"
        )
    return bool(bars_since_entry >= time_stop_bars and realized_r < 1.0)
