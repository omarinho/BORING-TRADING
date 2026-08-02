# REQ-015, REQ-019
"""CLI entrypoint tests: scan, size, journal-add, journal-eod-note, report-weekly.

cli.py is the last module in korkoban/ (design_decisions.package_layout) — it wires
sizing/journal/reports/ibkr_client together behind `python -m korkoban.cli <command>`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from korkoban import cli, config, exits, guardrails, journal


def test_size_command_prints_computed_units(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["size", "--net-liq", "100000", "--stop-distance", "10", "--point-value", "50"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units=1" in captured.out


def test_size_command_rejects_out_of_bounds_risk_pct(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        [
            "size",
            "--net-liq",
            "100000",
            "--stop-distance",
            "10",
            "--point-value",
            "50",
            "--risk-pct",
            "0.02",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "risk_pct" in captured.err


def test_journal_add_command_writes_entry_with_counted_in_stats(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            "journal-add",
            "--symbol",
            "ES",
            "--direction",
            "long",
            "--setup",
            "setup1",
            "--entry-price",
            "5000",
            "--stop-price",
            "4990",
            "--target-price",
            "5025",
            "--size",
            "1",
            "--risk-dollars",
            "500",
            "--checklist-gate-answer",
            "edge_based",
            "--reasoning",
            "clean breakout, matched every checklist condition",
            "--screenshot-path",
            "screenshots/es_20260105.png",
            "--journal-path",
            str(journal_path),
        ]
    )
    assert exit_code == 0
    entries = journal.read_all_entries(str(journal_path))
    assert len(entries) == 1
    assert entries[0].symbol == "ES"
    assert entries[0].counted_in_stats is True
    assert entries[0].reasoning == "clean breakout, matched every checklist condition"
    assert entries[0].screenshot_path == "screenshots/es_20260105.png"


def test_journal_add_command_rejects_invalid_checklist_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            "journal-add",
            "--symbol",
            "ES",
            "--direction",
            "long",
            "--setup",
            "setup1",
            "--entry-price",
            "5000",
            "--stop-price",
            "4990",
            "--target-price",
            "5025",
            "--size",
            "1",
            "--risk-dollars",
            "500",
            "--checklist-gate-answer",
            "not_a_real_answer",
            "--reasoning",
            "n/a",
            "--screenshot-path",
            "n/a",
            "--journal-path",
            str(journal_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert not journal_path.exists() or journal.read_all_entries(str(journal_path)) == []
    assert captured.err != ""


def test_journal_eod_note_command_writes_one_note(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            "journal-eod-note",
            "felt disciplined today",
            "--day",
            "2026-01-05",
            "--journal-path",
            str(journal_path),
        ]
    )
    assert exit_code == 0
    entries = journal.read_all_entries(str(journal_path))
    assert len(entries) == 1
    assert entries[0].entry_type == "eod_note"
    assert entries[0].note == "felt disciplined today"


def test_journal_eod_note_command_rejects_second_note_same_day(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    first = cli.main(
        ["journal-eod-note", "note one", "--day", "2026-01-05", "--journal-path", str(journal_path)]
    )
    second = cli.main(
        ["journal-eod-note", "note two", "--day", "2026-01-05", "--journal-path", str(journal_path)]
    )
    captured = capsys.readouterr()
    assert first == 0
    assert second != 0
    assert captured.err != ""
    assert len(journal.read_all_entries(str(journal_path))) == 1


def test_report_weekly_command_prints_all_four_figures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    journal.append_trade_entry(
        str(journal_path),
        journal.TradeJournalEntry(
            entry_type="trade",
            timestamp="2026-01-10T10:00:00",
            realized_r=1.5,
            checklist_gate_answer="edge_based",
        ),
    )
    exit_code = cli.main(
        [
            "report-weekly",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-31",
            "--journal-path",
            str(journal_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Expectancy" in captured.out
    assert "drawdown" in captured.out.lower()
    assert "Forced trade count" in captured.out
    assert "Zero-signal day count" in captured.out


def test_scan_command_reports_clear_message_when_gateway_unreachable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise_connection_error(_path: str) -> object:
        raise ConnectionError("no paper Gateway reachable")

    exit_code = cli.main(["scan"], client_factory=_raise_connection_error)
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "Gateway" in captured.err or "gateway" in captured.err


def test_no_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_never_imports_ib_insync_directly() -> None:
    # cli.py must go through ibkr_client, never touch ib_insync's IB object itself.
    source = (Path(__file__).resolve().parents[2] / "korkoban" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "import ib_insync" not in source
    assert "from ib_insync" not in source


# ─── REQ-008 (remediation round 1) — management plan must be computed by the real
# exits.compute_management_plan() function, never hand-typed by the CLI caller ──────────────


def _journal_add_base_args(journal_path: Path) -> list[str]:
    return [
        "journal-add",
        "--symbol",
        "ES",
        "--direction",
        "long",
        "--setup",
        "setup1",
        "--entry-price",
        "5000",
        "--stop-price",
        "4990",
        "--target-price",
        "5025",
        "--size",
        "1",
        "--risk-dollars",
        "500",
        "--checklist-gate-answer",
        "edge_based",
        "--reasoning",
        "clean breakout",
        "--screenshot-path",
        "screenshots/es.png",
        "--journal-path",
        str(journal_path),
    ]


def test_journal_add_with_management_plan_flag_calls_real_compute_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    real_compute = exits.compute_management_plan
    call_count = {"n": 0}

    def _spy(*args: object, **kwargs: object) -> exits.ManagementPlan:
        call_count["n"] += 1
        return real_compute(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli.exits, "compute_management_plan", _spy)

    exit_code = cli.main(
        [*_journal_add_base_args(journal_path), "--with-management-plan"]
    )
    assert exit_code == 0
    assert call_count["n"] == 1

    entries = journal.read_all_entries(str(journal_path))
    entry = entries[0]
    expected = real_compute()
    assert entry.scale_out_fraction == expected.scale_out_fraction
    assert entry.scale_out_r_multiple == expected.scale_out_r_multiple
    assert entry.trail_atr_multiple == expected.trail_atr_multiple


def test_journal_add_with_management_plan_overrides_are_passed_through_to_real_function(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            *_journal_add_base_args(journal_path),
            "--with-management-plan",
            "--scale-out-r-multiple",
            "2.0",
            "--trail-atr-multiple",
            "1.3",
        ]
    )
    assert exit_code == 0
    entry = journal.read_all_entries(str(journal_path))[0]
    assert entry.scale_out_r_multiple == 2.0
    assert entry.trail_atr_multiple == 1.3
    assert entry.scale_out_fraction == config.SCALE_OUT_FRACTION


def test_journal_add_without_management_plan_flag_leaves_plan_fields_none(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(_journal_add_base_args(journal_path))
    assert exit_code == 0
    entry = journal.read_all_entries(str(journal_path))[0]
    assert entry.scale_out_fraction is None
    assert entry.scale_out_r_multiple is None
    assert entry.trail_atr_multiple is None


# ─── REQ-011 (remediation round 1) — the emotional circuit breaker must actually block
# new trade logging and suppress the scan-alert path, persisted across CLI invocations ──────


def test_circuit_breaker_flip_persists_paused_state(tmp_path: Path) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"
    exit_code = cli.main(["circuit-breaker", "flip", "--state-path", str(state_path)])
    assert exit_code == 0
    state = guardrails.load_circuit_breaker_state(str(state_path))
    assert state.paused_since is not None


def test_journal_add_rejected_while_circuit_breaker_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"
    journal_path = tmp_path / "trade_journal.jsonl"
    flip_exit_code = cli.main(["circuit-breaker", "flip", "--state-path", str(state_path)])
    assert flip_exit_code == 0

    exit_code = cli.main(
        [*_journal_add_base_args(journal_path), "--circuit-breaker-path", str(state_path)]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "circuit breaker" in captured.err.lower()
    assert not journal_path.exists() or journal.read_all_entries(str(journal_path)) == []


def test_journal_add_allowed_when_circuit_breaker_never_flipped(tmp_path: Path) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"  # never created
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [*_journal_add_base_args(journal_path), "--circuit-breaker-path", str(state_path)]
    )
    assert exit_code == 0
    assert len(journal.read_all_entries(str(journal_path))) == 1


def test_scan_command_suppresses_alert_when_circuit_breaker_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"
    flip_exit_code = cli.main(["circuit-breaker", "flip", "--state-path", str(state_path)])
    assert flip_exit_code == 0

    def _fake_connect(_path: str) -> object:
        return object()

    exit_code = cli.main(
        ["scan", "--circuit-breaker-path", str(state_path)], client_factory=_fake_connect
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "circuit breaker" in (captured.out + captured.err).lower()


# ─── REQ-010 (remediation round 2) — three consecutive winning trades logged through the
# real CLI must actually throttle the effective risk_pct used by the next `size` invocation,
# via the real guardrails.update_win_streak_state()/risk_pct_for_state() functions ──────────


def test_journal_add_three_wins_then_size_command_uses_throttled_risk_pct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    win_streak_path = tmp_path / "win_streak_state.json"

    real_update = guardrails.update_win_streak_state
    update_calls = {"n": 0}

    def _update_spy(*args: object, **kwargs: object) -> guardrails.WinStreakState:
        update_calls["n"] += 1
        return real_update(*args, **kwargs)  # type: ignore[arg-type]

    real_risk = guardrails.risk_pct_for_state
    risk_calls = {"n": 0}

    def _risk_spy(*args: object, **kwargs: object) -> float:
        risk_calls["n"] += 1
        return real_risk(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli.guardrails, "update_win_streak_state", _update_spy)
    monkeypatch.setattr(cli.guardrails, "risk_pct_for_state", _risk_spy)

    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        exit_code = cli.main(
            [
                *_journal_add_base_args(journal_path),
                "--realized-r",
                "1.0",
                "--win-streak-path",
                str(win_streak_path),
            ]
        )
        assert exit_code == 0

    assert update_calls["n"] == config.WIN_STREAK_TRIGGER_COUNT
    state_after_wins = guardrails.load_win_streak_state(str(win_streak_path))
    assert state_after_wins.throttle_trades_remaining == config.WIN_STREAK_THROTTLE_TRADE_COUNT

    size_exit_code = cli.main(
        [
            "size",
            "--net-liq",
            "100000",
            "--stop-distance",
            "10",
            "--point-value",
            "50",
            "--win-streak-path",
            str(win_streak_path),
        ]
    )
    captured = capsys.readouterr()
    assert size_exit_code == 0
    assert risk_calls["n"] == 1

    expected_risk_pct = config.RISK_PCT_DEFAULT * (1 - config.WIN_STREAK_RISK_REDUCTION_PCT)
    from korkoban import sizing

    expected = sizing.compute_size(
        net_liq=100000,
        stop_distance_points=10,
        point_value=50,
        risk_pct=expected_risk_pct,
        enforce_risk_pct_bounds=False,
    )
    assert f"risk_dollars={expected.risk_dollars}" in captured.out


def test_size_command_uses_default_risk_pct_when_no_win_streak_state(
    tmp_path: Path,
) -> None:
    win_streak_path = tmp_path / "win_streak_state.json"  # never created
    exit_code = cli.main(
        [
            "size",
            "--net-liq",
            "100000",
            "--stop-distance",
            "10",
            "--point-value",
            "50",
            "--win-streak-path",
            str(win_streak_path),
        ]
    )
    assert exit_code == 0


def test_win_streak_status_reports_inactive_when_never_triggered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "win_streak_state.json"  # never created
    exit_code = cli.main(["win-streak", "status", "--state-path", str(state_path)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "inactive" in captured.out.lower()


def test_win_streak_status_reports_active_after_three_wins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    state_path = tmp_path / "win_streak_state.json"
    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        exit_code = cli.main(
            [
                *_journal_add_base_args(journal_path),
                "--realized-r",
                "1.0",
                "--win-streak-path",
                str(state_path),
            ]
        )
        assert exit_code == 0

    status_exit_code = cli.main(["win-streak", "status", "--state-path", str(state_path)])
    captured = capsys.readouterr()
    assert status_exit_code == 0
    assert "active" in captured.out.lower()
    assert str(config.WIN_STREAK_THROTTLE_TRADE_COUNT) in captured.out


def test_scan_command_proceeds_when_circuit_breaker_not_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"  # never flipped

    def _fake_connect(_path: str) -> object:
        return object()

    exit_code = cli.main(
        ["scan", "--circuit-breaker-path", str(state_path)], client_factory=_fake_connect
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "circuit breaker" not in (captured.out + captured.err).lower()
