"""Position sizing math: how many units to trade for a given risk budget."""

from __future__ import annotations

import math
from dataclasses import dataclass

from korkoban import config


@dataclass(frozen=True)
class PositionSize:
    units: int
    risk_dollars: float
    dollars_per_unit: float


def compute_size(
    net_liq: float,
    stop_distance_points: float,
    point_value: float,
    risk_pct: float = config.RISK_PCT_DEFAULT,
    enforce_risk_pct_bounds: bool = True,
) -> PositionSize:
    # The [RISK_PCT_MIN, RISK_PCT_MAX] band is a sanity check on raw, user-supplied risk_pct
    # input (catches fat-finger CLI typos). A guardrail-derived value — e.g. the win-streak
    # throttle in guardrails.risk_pct_for_state(), which deliberately reduces risk below the
    # normal floor as a safety measure (REQ-010) — is not a user input error, so callers that
    # already validated the base risk_pct may pass enforce_risk_pct_bounds=False.
    if enforce_risk_pct_bounds and not (config.RISK_PCT_MIN <= risk_pct <= config.RISK_PCT_MAX):
        raise ValueError(
            f"risk_pct {risk_pct} outside bounds " f"[{config.RISK_PCT_MIN}, {config.RISK_PCT_MAX}]"
        )

    risk_dollars = net_liq * risk_pct
    dollars_per_unit = stop_distance_points * point_value

    if dollars_per_unit <= 0:
        return PositionSize(units=0, risk_dollars=risk_dollars, dollars_per_unit=dollars_per_unit)

    # Floor, never round up — sizing must never take on more risk than the budget allows.
    units = math.floor(risk_dollars / dollars_per_unit)
    return PositionSize(units=units, risk_dollars=risk_dollars, dollars_per_unit=dollars_per_unit)


def point_value_for(symbol: str) -> float:
    return config.FUTURES_POINT_VALUES[symbol]
