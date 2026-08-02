# REQ-007, REQ-008, REQ-009
from __future__ import annotations

import inspect
import re

import pytest

from korkoban import config
from korkoban import exits as exits_module
from korkoban.exits import (
    ManagementPlan,
    check_time_stop,
    compute_initial_stop,
    compute_management_plan,
    compute_target,
)


def test_tc_007_01_long_stop_below_entry() -> None:
    stop = compute_initial_stop(
        entry_price=100.0, atr14=4.0, direction="long", stop_atr_multiple=1.5
    )
    assert stop == pytest.approx(100.0 - 1.5 * 4.0)


def test_tc_007_02_short_stop_above_entry() -> None:
    stop = compute_initial_stop(
        entry_price=100.0, atr14=4.0, direction="short", stop_atr_multiple=1.5
    )
    assert stop == pytest.approx(100.0 + 1.5 * 4.0)


def test_tc_007_03_stop_multiple_below_min_rejected() -> None:
    with pytest.raises(ValueError):
        compute_initial_stop(entry_price=100.0, atr14=4.0, direction="long", stop_atr_multiple=1.2)


def test_tc_007_04_stop_multiple_above_max_rejected() -> None:
    with pytest.raises(ValueError):
        compute_initial_stop(entry_price=100.0, atr14=4.0, direction="long", stop_atr_multiple=1.7)


def test_tc_007_05_default_stop_multiple_applied_when_omitted() -> None:
    stop = compute_initial_stop(entry_price=100.0, atr14=4.0, direction="long")
    assert stop == pytest.approx(100.0 - config.STOP_ATR_MULTIPLE_DEFAULT * 4.0)


def test_invalid_direction_rejected() -> None:
    with pytest.raises(ValueError):
        compute_initial_stop(entry_price=100.0, atr14=4.0, direction="sideways")


def test_tc_007_06_structural_audit_no_widen_or_recompute_and_no_prior_stop_param() -> None:
    source_path = inspect.getsourcefile(exits_module)
    assert source_path is not None
    with open(source_path, encoding="utf-8") as handle:
        full_source = handle.read()

    forbidden_function_name_fragments = (
        "widen_stop",
        "update_stop",
        "recompute_stop",
        "adjust_stop",
    )
    function_names = re.findall(r"^def\s+(\w+)\s*\(", full_source, flags=re.MULTILINE)
    for name in function_names:
        for fragment in forbidden_function_name_fragments:
            assert fragment not in name, f"found forbidden function name pattern: {name}"

    signature = inspect.signature(compute_initial_stop)
    forbidden_param_fragments = ("existing_stop", "current_stop", "prior_stop")
    for param_name in signature.parameters:
        for fragment in forbidden_param_fragments:
            assert fragment not in param_name, (
                f"compute_initial_stop must not accept a parameter like {param_name}"
            )


def test_tc_008_01_target_long_case() -> None:
    entry_price = 100.0
    initial_stop = 94.0  # initial_risk = 6.0
    target = compute_target(
        entry_price=entry_price,
        initial_stop=initial_stop,
        direction="long",
        target_r_multiple=2.5,
    )
    assert target == pytest.approx(100.0 + 2.5 * 6.0)


def test_tc_008_02_target_multiple_below_min_rejected() -> None:
    with pytest.raises(ValueError):
        compute_target(
            entry_price=100.0, initial_stop=94.0, direction="long", target_r_multiple=2.1
        )


def test_tc_008_03_target_multiple_above_max_rejected() -> None:
    with pytest.raises(ValueError):
        compute_target(
            entry_price=100.0, initial_stop=94.0, direction="long", target_r_multiple=2.9
        )


def test_tc_008_04_default_target_multiple_applied_when_omitted() -> None:
    target = compute_target(entry_price=100.0, initial_stop=94.0, direction="long")
    assert target == pytest.approx(100.0 + config.TARGET_R_MULTIPLE_DEFAULT * 6.0)


def test_target_short_case() -> None:
    entry_price = 100.0
    initial_stop = 106.0  # initial_risk = 6.0
    target = compute_target(
        entry_price=entry_price,
        initial_stop=initial_stop,
        direction="short",
        target_r_multiple=2.5,
    )
    assert target == pytest.approx(100.0 - 2.5 * 6.0)


def test_tc_008_05_management_plan_defaults() -> None:
    plan = compute_management_plan()
    assert plan == ManagementPlan(
        scale_out_fraction=0.5,
        scale_out_r_multiple=1.8,
        trail_atr_multiple=1.5,
    )


def test_tc_009_01_time_stop_flagged() -> None:
    assert check_time_stop(bars_since_entry=10, realized_r=0.5) is True


def test_tc_009_02_time_stop_not_yet_reached() -> None:
    assert check_time_stop(bars_since_entry=9, realized_r=0.5) is False


def test_tc_009_03_time_stop_not_flagged_when_realized_r_above_one() -> None:
    assert check_time_stop(bars_since_entry=10, realized_r=1.2) is False


def test_tc_009_04_time_stop_bars_below_min_rejected() -> None:
    with pytest.raises(ValueError):
        check_time_stop(bars_since_entry=10, realized_r=0.5, time_stop_bars=7)


def test_tc_009_05_time_stop_bars_above_max_rejected() -> None:
    with pytest.raises(ValueError):
        check_time_stop(bars_since_entry=10, realized_r=0.5, time_stop_bars=13)


def test_tc_009_06_check_time_stop_returns_plain_bool() -> None:
    result = check_time_stop(bars_since_entry=10, realized_r=0.5)
    assert isinstance(result, bool)
    assert type(result) is bool
