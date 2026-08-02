# REQ-006, REQ-021
from __future__ import annotations

import dataclasses
import inspect

import pytest

from korkoban import config
from korkoban import sizing as sizing_module
from korkoban.sizing import PositionSize, compute_size, point_value_for


def test_tc_006_01_standard_size_computation() -> None:
    result = compute_size(
        net_liq=100_000.0,
        stop_distance_points=10.0,
        point_value=point_value_for("ES"),
        risk_pct=0.005,
    )
    assert result.units == 1
    assert result.risk_dollars == pytest.approx(500.0)
    assert result.dollars_per_unit == pytest.approx(500.0)


def test_tc_006_02_floors_down_never_rounds_up() -> None:
    # net_liq * risk_pct = risk_dollars; dollars_per_unit = stop_distance_points * point_value
    # choose numbers so risk_dollars / dollars_per_unit == 0.9 exactly
    net_liq = 100_000.0
    risk_pct = 0.0045  # risk_dollars = 450.0
    point_value = 50.0
    stop_distance_points = 10.0  # dollars_per_unit = 500.0 -> ratio = 0.9
    result = compute_size(
        net_liq=net_liq,
        stop_distance_points=stop_distance_points,
        point_value=point_value,
        risk_pct=risk_pct,
    )
    assert result.units == 0


def test_tc_006_03_risk_pct_below_min_rejected() -> None:
    with pytest.raises(ValueError):
        compute_size(
            net_liq=100_000.0,
            stop_distance_points=10.0,
            point_value=50.0,
            risk_pct=0.003,
        )


def test_tc_006_04_risk_pct_above_max_rejected() -> None:
    with pytest.raises(ValueError):
        compute_size(
            net_liq=100_000.0,
            stop_distance_points=10.0,
            point_value=50.0,
            risk_pct=0.008,
        )


def test_tc_006_05_default_risk_pct_applied_when_omitted() -> None:
    result = compute_size(
        net_liq=100_000.0,
        stop_distance_points=10.0,
        point_value=50.0,
    )
    assert result.risk_dollars == pytest.approx(100_000.0 * config.RISK_PCT_DEFAULT)


def test_tc_006_06_net_liq_drives_risk_dollars_proportionally() -> None:
    small = compute_size(
        net_liq=50_000.0,
        stop_distance_points=10.0,
        point_value=50.0,
        risk_pct=0.005,
    )
    large = compute_size(
        net_liq=100_000.0,
        stop_distance_points=10.0,
        point_value=50.0,
        risk_pct=0.005,
    )
    assert large.risk_dollars == pytest.approx(2 * small.risk_dollars)


def test_tc_021_02_point_value_sourced_only_via_point_value_for() -> None:
    # point_value_for must look up config.FUTURES_POINT_VALUES, not an inline literal
    source = inspect.getsource(point_value_for)
    assert "FUTURES_POINT_VALUES" in source

    # No other point-value literal (the actual numbers from FUTURES_POINT_VALUES) may
    # appear anywhere in sizing.py outside point_value_for's own body.
    source_path = inspect.getsourcefile(sizing_module)
    assert source_path is not None
    with open(source_path, encoding="utf-8") as handle:
        full_source = handle.read()
    remainder = full_source.replace(source, "")
    for point_value in config.FUTURES_POINT_VALUES.values():
        literal = repr(point_value)
        assert literal not in remainder, (
            f"found suspicious point-value literal {literal} outside point_value_for"
        )


def test_point_value_for_looks_up_config_dict() -> None:
    assert point_value_for("ES") == config.FUTURES_POINT_VALUES["ES"]
    assert point_value_for("MES") == config.FUTURES_POINT_VALUES["MES"]


# REQ-010 (remediation round 2) — the win-streak guardrail throttle can legitimately push the
# effective risk_pct below config.RISK_PCT_MIN (e.g. 0.005 * 0.75 = 0.00375 < 0.004); that is a
# deliberate safety reduction, not a user-input error, so compute_size must allow the bounds
# check to be bypassed for guardrail-derived values while keeping it enforced by default.
def test_compute_size_allows_risk_pct_below_min_when_bounds_not_enforced() -> None:
    result = compute_size(
        net_liq=100_000.0,
        stop_distance_points=10.0,
        point_value=50.0,
        risk_pct=0.00375,
        enforce_risk_pct_bounds=False,
    )
    assert result.risk_dollars == pytest.approx(375.0)


def test_compute_size_still_enforces_bounds_by_default_when_flag_omitted() -> None:
    with pytest.raises(ValueError):
        compute_size(
            net_liq=100_000.0,
            stop_distance_points=10.0,
            point_value=50.0,
            risk_pct=0.00375,
        )


def test_position_size_is_frozen_dataclass() -> None:
    result = PositionSize(units=1, risk_dollars=500.0, dollars_per_unit=500.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.units = 2  # type: ignore[misc]
