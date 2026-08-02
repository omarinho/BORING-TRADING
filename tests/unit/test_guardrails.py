# REQ-010, REQ-011, REQ-012, REQ-013
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from korkoban import config, journal
from korkoban.guardrails import (
    DEFAULT_CIRCUIT_BREAKER_STATE_PATH,
    DEFAULT_WIN_STREAK_STATE_PATH,
    ChecklistGateAnswer,
    CircuitBreakerState,
    WinStreakState,
    can_alert,
    can_log_trade,
    check_overtrading,
    count_trades_in_month,
    counted_in_stats,
    flip_circuit_breaker,
    is_paused,
    load_circuit_breaker_state,
    load_win_streak_state,
    risk_pct_for_state,
    save_circuit_breaker_state,
    save_win_streak_state,
    update_win_streak_state,
    validate_checklist_gate_answer,
)
from korkoban.journal import TradeJournalEntry


def test_tc_010_01_three_consecutive_wins_trigger_throttled_risk(tmp_path: object) -> None:
    state = WinStreakState()
    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        state = update_win_streak_state(state, realized_r=1.0)
    expected = config.RISK_PCT_DEFAULT * (1 - config.WIN_STREAK_RISK_REDUCTION_PCT)
    assert risk_pct_for_state(state, base_risk_pct=config.RISK_PCT_DEFAULT) == pytest.approx(
        expected
    )


def test_tc_010_02_loss_after_two_wins_resets_streak_counter() -> None:
    state = WinStreakState()
    state = update_win_streak_state(state, realized_r=1.0)
    state = update_win_streak_state(state, realized_r=1.0)
    state = update_win_streak_state(state, realized_r=-1.0)
    assert state.consecutive_wins == 0
    state = update_win_streak_state(state, realized_r=1.0)
    assert state.consecutive_wins == 1


def test_tc_010_03_throttle_active_for_exactly_twelve_trades_then_reverts() -> None:
    state = WinStreakState()
    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        state = update_win_streak_state(state, realized_r=1.0)
    assert state.throttle_trades_remaining == config.WIN_STREAK_THROTTLE_TRADE_COUNT
    # feed losses (non-wins) through the throttle window so the streak counter stays quiet
    for _i in range(config.WIN_STREAK_THROTTLE_TRADE_COUNT):
        assert risk_pct_for_state(state) < config.RISK_PCT_DEFAULT
        state = update_win_streak_state(state, realized_r=-1.0)
    assert state.throttle_trades_remaining == 0
    assert risk_pct_for_state(state) == pytest.approx(config.RISK_PCT_DEFAULT)


def test_tc_010_04_win_during_active_throttle_does_not_stack_second_reduction() -> None:
    state = WinStreakState()
    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        state = update_win_streak_state(state, realized_r=1.0)
    assert state.throttle_trades_remaining == config.WIN_STREAK_THROTTLE_TRADE_COUNT
    # a win right away during the active throttle must not re-trigger/extend the throttle
    state = update_win_streak_state(state, realized_r=1.0)
    assert state.throttle_trades_remaining == config.WIN_STREAK_THROTTLE_TRADE_COUNT - 1


def test_tc_010_05_risk_pct_never_exceeds_base_across_state_machine() -> None:
    state = WinStreakState()
    realized_rs = [1.0, 1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0]
    for r in realized_rs:
        state = update_win_streak_state(state, realized_r=r)
        assert risk_pct_for_state(state, base_risk_pct=config.RISK_PCT_DEFAULT) <= (
            config.RISK_PCT_DEFAULT
        )


def test_tc_011_01_flag_set_suppresses_alerts_for_window() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0)
    state = CircuitBreakerState()
    state = flip_circuit_breaker(state, now=t)
    assert can_alert(state, now=t) is False
    mid_window = t + timedelta(days=3)
    assert can_alert(state, now=mid_window) is False


def test_tc_011_02_new_trade_logging_rejected_mid_pause() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0)
    state = CircuitBreakerState()
    state = flip_circuit_breaker(state, now=t)
    mid_window = t + timedelta(days=3)
    assert can_log_trade(state, now=mid_window) is False


def test_tc_011_03_alerts_and_logging_resume_at_exactly_seven_days() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0)
    state = CircuitBreakerState()
    state = flip_circuit_breaker(state, now=t)
    exactly_seven_days = t + timedelta(days=config.EMOTIONAL_PAUSE_DAYS)
    assert can_alert(state, now=exactly_seven_days) is True
    assert can_log_trade(state, now=exactly_seven_days) is True


def test_tc_011_04_reflipping_during_active_pause_does_not_shorten_or_reset() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0)
    state = CircuitBreakerState()
    state = flip_circuit_breaker(state, now=t)
    later = t + timedelta(days=5)
    state = flip_circuit_breaker(state, now=later)
    assert state.paused_since == t
    # the window is still anchored to the original T, not the re-flip time
    exactly_seven_days_from_original = t + timedelta(days=config.EMOTIONAL_PAUSE_DAYS)
    assert is_paused(state, now=exactly_seven_days_from_original) is False


def test_tc_011_05_one_second_before_seven_days_still_rejected() -> None:
    t = datetime(2026, 1, 1, 12, 0, 0)
    state = CircuitBreakerState()
    state = flip_circuit_breaker(state, now=t)
    almost_seven_days = t + timedelta(days=config.EMOTIONAL_PAUSE_DAYS) - timedelta(seconds=1)
    assert is_paused(state, now=almost_seven_days) is True


def test_tc_012_01_sixteenth_trade_in_month_with_threshold_15_warns() -> None:
    assert check_overtrading(trade_count_this_month=16, threshold=15) is True


def test_tc_012_02_exactly_fifteen_trades_threshold_15_no_warning() -> None:
    assert check_overtrading(trade_count_this_month=15, threshold=15) is False


def test_tc_012_03_prior_month_trades_dont_count_toward_current_month() -> None:
    timestamps = [
        datetime(2025, 12, 30, 10, 0, 0),
        datetime(2025, 12, 31, 10, 0, 0),
        datetime(2026, 1, 1, 10, 0, 0),
        datetime(2026, 1, 2, 10, 0, 0),
    ]
    assert count_trades_in_month(timestamps, year=2026, month=1) == 2


def test_tc_012_04_threshold_eleven_rejected() -> None:
    with pytest.raises(ValueError):
        check_overtrading(trade_count_this_month=5, threshold=config.OVERTRADING_THRESHOLD_MIN - 1)


def test_tc_012_05_threshold_sixteen_rejected() -> None:
    with pytest.raises(ValueError):
        check_overtrading(trade_count_this_month=5, threshold=config.OVERTRADING_THRESHOLD_MAX + 1)


def test_tc_012_06_overtrading_warning_never_blocks_trade_logging(tmp_path: object) -> None:
    assert check_overtrading(trade_count_this_month=20, threshold=15) is True
    journal_path = str(tmp_path / "journal.jsonl")  # type: ignore[operator]
    entry = TradeJournalEntry(
        entry_type="trade",
        timestamp="2026-01-05T10:00:00",
        symbol="ES",
        direction="long",
        setup="breakout",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        size=1,
        risk_dollars=500.0,
        realized_r=1.0,
        checklist_gate_answer=ChecklistGateAnswer.EDGE_BASED.value,
    )
    persisted = journal.append_trade_entry(journal_path, entry)
    assert persisted.symbol == "ES"


def test_tc_013_01_missing_checklist_gate_answer_rejected() -> None:
    with pytest.raises(ValueError):
        validate_checklist_gate_answer(None)


def test_counted_in_stats_true_only_for_edge_based() -> None:
    assert counted_in_stats(ChecklistGateAnswer.EDGE_BASED) is True
    assert counted_in_stats(ChecklistGateAnswer.IMPULSE) is False


# REQ-011 (remediation round 1) — CircuitBreakerState must survive across CLI invocations,
# so it needs a local structured-file persistence pair, consistent with journal.py's pattern.
def test_circuit_breaker_state_round_trips_through_persistence(tmp_path: Path) -> None:
    path = str(tmp_path / "circuit_breaker_state.json")
    state = CircuitBreakerState(paused_since=datetime(2026, 1, 1, 12, 0, 0))
    save_circuit_breaker_state(path, state)
    loaded = load_circuit_breaker_state(path)
    assert loaded == state


def test_load_circuit_breaker_state_missing_file_returns_default_unpaused(tmp_path: Path) -> None:
    path = str(tmp_path / "does_not_exist.json")
    loaded = load_circuit_breaker_state(path)
    assert loaded == CircuitBreakerState()
    assert loaded.paused_since is None


def test_default_circuit_breaker_state_path_is_relative_and_under_repo() -> None:
    path = Path(DEFAULT_CIRCUIT_BREAKER_STATE_PATH)
    assert not path.is_absolute()
    assert DEFAULT_CIRCUIT_BREAKER_STATE_PATH == "data/circuit_breaker_state.json"


# REQ-010 (remediation round 2) — WinStreakState must survive across CLI invocations, mirroring
# the exact load/save-to-local-JSON-file pattern already proven for CircuitBreakerState above.
def test_win_streak_state_round_trips_through_persistence(tmp_path: Path) -> None:
    path = str(tmp_path / "win_streak_state.json")
    state = WinStreakState(consecutive_wins=2, throttle_trades_remaining=5)
    save_win_streak_state(path, state)
    loaded = load_win_streak_state(path)
    assert loaded == state


def test_load_win_streak_state_missing_file_returns_default_untouched(tmp_path: Path) -> None:
    path = str(tmp_path / "does_not_exist.json")
    loaded = load_win_streak_state(path)
    assert loaded == WinStreakState()
    assert loaded.consecutive_wins == 0
    assert loaded.throttle_trades_remaining == 0


def test_default_win_streak_state_path_is_relative_and_under_repo() -> None:
    path = Path(DEFAULT_WIN_STREAK_STATE_PATH)
    assert not path.is_absolute()
    assert DEFAULT_WIN_STREAK_STATE_PATH == "data/win_streak_state.json"
