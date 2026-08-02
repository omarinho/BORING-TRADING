"""Win-streak throttle, emotional-pause circuit breaker, overtrading guard, checklist gate."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

from korkoban import config

# Local structured-file persistence for CircuitBreakerState — same pattern as journal.py's
# JSON Lines file: a plain local file, no DB server, so the flag/start-date survive across
# separate `python -m korkoban.cli` invocations (REQ-011).
DEFAULT_CIRCUIT_BREAKER_STATE_PATH: str = "data/circuit_breaker_state.json"

# Same local-JSON-file persistence pattern, applied to WinStreakState so the throttle counter
# survives across separate `python -m korkoban.cli` invocations (REQ-010).
DEFAULT_WIN_STREAK_STATE_PATH: str = "data/win_streak_state.json"


@dataclass(frozen=True)
class WinStreakState:
    consecutive_wins: int = 0
    throttle_trades_remaining: int = 0


def update_win_streak_state(state: WinStreakState, realized_r: float) -> WinStreakState:
    was_throttled = state.throttle_trades_remaining > 0
    remaining = state.throttle_trades_remaining - 1 if was_throttled else 0
    consecutive_wins = state.consecutive_wins + 1 if realized_r > 0 else 0
    # a win during an active throttle never stacks/extends a second reduction
    if consecutive_wins >= config.WIN_STREAK_TRIGGER_COUNT and not was_throttled:
        remaining = config.WIN_STREAK_THROTTLE_TRADE_COUNT
        consecutive_wins = 0
    return WinStreakState(consecutive_wins=consecutive_wins, throttle_trades_remaining=remaining)


def risk_pct_for_state(
    state: WinStreakState, base_risk_pct: float = config.RISK_PCT_DEFAULT
) -> float:
    if state.throttle_trades_remaining > 0:
        return base_risk_pct * (1 - config.WIN_STREAK_RISK_REDUCTION_PCT)
    return base_risk_pct


def load_win_streak_state(path: str = DEFAULT_WIN_STREAK_STATE_PATH) -> WinStreakState:
    """Reads WinStreakState from `path`; a missing file means a fresh, unthrottled state."""
    file_path = Path(path)
    if not file_path.exists():
        return WinStreakState()
    with file_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return WinStreakState(
        consecutive_wins=raw.get("consecutive_wins", 0),
        throttle_trades_remaining=raw.get("throttle_trades_remaining", 0),
    )


def save_win_streak_state(path: str, state: WinStreakState) -> None:
    """Persists WinStreakState to `path` so it survives across separate CLI invocations."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(state), f)


@dataclass(frozen=True)
class CircuitBreakerState:
    paused_since: datetime | None = None


def is_paused(
    state: CircuitBreakerState, now: datetime, pause_days: int = config.EMOTIONAL_PAUSE_DAYS
) -> bool:
    if state.paused_since is None:
        return False
    return now < state.paused_since + timedelta(days=pause_days)


def flip_circuit_breaker(state: CircuitBreakerState, now: datetime) -> CircuitBreakerState:
    if is_paused(state, now):
        return state  # re-flipping early doesn't shorten/reset an active pause
    return CircuitBreakerState(paused_since=now)


def can_alert(state: CircuitBreakerState, now: datetime) -> bool:
    return not is_paused(state, now)


def can_log_trade(state: CircuitBreakerState, now: datetime) -> bool:
    return not is_paused(state, now)


def load_circuit_breaker_state(
    path: str = DEFAULT_CIRCUIT_BREAKER_STATE_PATH,
) -> CircuitBreakerState:
    """Reads CircuitBreakerState from `path`; a missing file means never-paused (default)."""
    file_path = Path(path)
    if not file_path.exists():
        return CircuitBreakerState()
    with file_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    paused_since = raw.get("paused_since")
    return CircuitBreakerState(
        paused_since=datetime.fromisoformat(paused_since) if paused_since is not None else None
    )


def save_circuit_breaker_state(path: str, state: CircuitBreakerState) -> None:
    """Persists CircuitBreakerState to `path` so it survives across separate CLI invocations."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    raw = asdict(state)
    raw["paused_since"] = state.paused_since.isoformat() if state.paused_since is not None else None
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(raw, f)


def check_overtrading(
    trade_count_this_month: int, threshold: int = config.OVERTRADING_THRESHOLD_DEFAULT
) -> bool:
    if not (config.OVERTRADING_THRESHOLD_MIN <= threshold <= config.OVERTRADING_THRESHOLD_MAX):
        raise ValueError(
            f"threshold {threshold} outside allowed range "
            f"[{config.OVERTRADING_THRESHOLD_MIN}, {config.OVERTRADING_THRESHOLD_MAX}]"
        )
    return trade_count_this_month > threshold


def count_trades_in_month(trade_timestamps: list[datetime], year: int, month: int) -> int:
    return sum(1 for ts in trade_timestamps if ts.year == year and ts.month == month)


class ChecklistGateAnswer(StrEnum):
    EDGE_BASED = "edge_based"
    IMPULSE = "impulse"


def validate_checklist_gate_answer(answer: str | None) -> ChecklistGateAnswer:
    if answer is None:
        raise ValueError("checklist_gate_answer is required for every valid-signal trade log")
    return ChecklistGateAnswer(answer)


def counted_in_stats(answer: ChecklistGateAnswer) -> bool:
    return answer is ChecklistGateAnswer.EDGE_BASED
