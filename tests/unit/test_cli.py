# REQ-015, REQ-019
"""CLI entrypoint tests: scan, size, journal-add, journal-eod-note, report-weekly.

cli.py is the last module in korkoban/ (design_decisions.package_layout) — it wires
sizing/journal/reports/ibkr_client together behind `python -m korkoban.cli <command>`.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from korkoban import cli, config, exits, guardrails, journal, setups


def test_size_command_prints_computed_units(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["size", "--net-liq", "100000", "--stop-distance", "10", "--point-value", "50"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units=1" in captured.out


def test_size_command_derives_point_value_from_futures_symbol(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(["size", "--net-liq", "100000", "--stop-distance", "10", "--symbol", "ES"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"dollars_per_unit={10 * config.FUTURES_POINT_VALUES['ES']}" in captured.out


def test_size_command_derives_point_value_of_one_for_non_futures_symbol(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(
        ["size", "--net-liq", "100000", "--stop-distance", "10", "--symbol", "AAPL"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "dollars_per_unit=10.0" in captured.out


def test_size_command_explicit_point_value_overrides_symbol_lookup(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(
        [
            "size",
            "--net-liq",
            "100000",
            "--stop-distance",
            "10",
            "--symbol",
            "ES",
            "--point-value",
            "999",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "dollars_per_unit=9990.0" in captured.out


def test_size_command_requires_symbol_or_point_value(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["size", "--net-liq", "100000", "--stop-distance", "10"])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "--symbol" in captured.err or "--point-value" in captured.err


# ─── size command NetLiq wiring (REQ-006) — capital base fetched live from
# IBKRClient.account_net_liquidation() when --net-liq is omitted, per INSTRUCTIONS.md ───────


def test_size_command_uses_explicit_net_liq_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail_if_called(_path: str) -> object:
        raise AssertionError("client_factory must not be called when --net-liq is given")

    exit_code = cli.main(
        ["size", "--net-liq", "100000", "--stop-distance", "10", "--point-value", "50"],
        client_factory=_fail_if_called,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units=1" in captured.out


def test_size_command_fetches_net_liq_from_ibkr_when_omitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _FakeScanClient(net_liq=100_000.0)

    exit_code = cli.main(
        ["size", "--stop-distance", "10", "--point-value", "50"],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "units=1" in captured.out


def test_size_command_reports_error_when_net_liq_omitted_and_gateway_unreachable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _raise_connection_error(_path: str) -> object:
        raise ConnectionError("no paper Gateway reachable")

    exit_code = cli.main(
        ["size", "--stop-distance", "10", "--point-value", "50"],
        client_factory=_raise_connection_error,
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "Gateway" in captured.err or "gateway" in captured.err


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
    # --win-streak-path is scoped to journal_path's own tmp_path by default so every test
    # using this helper stays isolated from the real data/win_streak_state.json — a caller
    # that wants to exercise win-streak behavior explicitly can still append its own
    # --win-streak-path afterward (argparse keeps the last value for a repeated option).
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
        "--win-streak-path",
        str(journal_path.parent / "win_streak_state.json"),
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

    exit_code = cli.main([*_journal_add_base_args(journal_path), "--with-management-plan"])
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

    exit_code = cli.main(
        ["scan", "--circuit-breaker-path", str(state_path)],
        client_factory=lambda _path: _FakeScanClient(),
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "circuit breaker" in (captured.out + captured.err).lower()


# ─── Scan wiring (REQ-002/003 end-to-end) — futures universe -> historical bars via a fake
# client -> setups.is_breakout/is_pullback -> printed alert + persisted breakout state ──────


class _FakeScanClient:
    def __init__(
        self,
        bars_by_symbol: dict[str, list[setups.Bar]] | None = None,
        stock_symbols: list[str] | None = None,
        stock_bars_by_symbol: dict[str, list[setups.Bar]] | None = None,
        stock_spread_by_symbol: dict[str, float] | None = None,
        stock_adv_by_symbol: dict[str, float] | None = None,
        net_liq: float | None = None,
    ) -> None:
        self._bars_by_symbol = bars_by_symbol or {}
        self._stock_symbols = stock_symbols or []
        self._stock_bars_by_symbol = stock_bars_by_symbol or {}
        self._stock_spread_by_symbol = stock_spread_by_symbol or {}
        self._stock_adv_by_symbol = stock_adv_by_symbol or {}
        self._net_liq = net_liq

    def account_net_liquidation(self) -> float:
        if self._net_liq is None:
            raise ValueError("no NetLiq configured on this fake client")
        return self._net_liq

    def historical_futures_bars(
        self, symbol: str, duration: str = "2 Y", bar_size: str = "1 day"
    ) -> list[setups.Bar]:
        return self._bars_by_symbol.get(symbol, [])

    def historical_stock_bars(
        self, symbol: str, duration: str = "2 Y", bar_size: str = "1 day"
    ) -> list[setups.Bar]:
        return self._stock_bars_by_symbol.get(symbol, [])

    def stock_candidate_symbols(self) -> list[str]:
        return self._stock_symbols

    def stock_bid_ask_spread_pct(self, symbol: str) -> float:
        if symbol not in self._stock_spread_by_symbol:
            raise ValueError(f"no live quote for {symbol}")
        return self._stock_spread_by_symbol[symbol]

    def stock_average_daily_volume(self, symbol: str) -> float:
        if symbol not in self._stock_adv_by_symbol:
            raise ValueError(f"no volume history for {symbol}")
        return self._stock_adv_by_symbol[symbol]

    def disconnect(self) -> None:
        pass


def _scan_dates(n: int) -> list[str]:
    start = date(2020, 1, 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _scan_bar(day: str, mid: float, true_range: float, volume: float) -> setups.Bar:
    return setups.Bar(
        date=day,
        open=mid,
        high=mid + true_range / 2,
        low=mid - true_range / 2,
        close=mid,
        volume=volume,
    )


def _clean_long_breakout_bars() -> list[setups.Bar]:
    """A minimal bar series satisfying all four Setup-1 conditions for a long breakout —
    same construction as test_setups.py's `_breakout_bars(direction="long")` default, kept
    local so CLI-level scan-wiring tests don't couple to test_setups.py's internals.
    """
    n = config.ATR_PERIOD + config.ATR_PERCENTILE_WINDOW_DAYS + 1
    dates = _scan_dates(n)
    trend_rate = 0.002
    base_price = 1000.0

    mids = [base_price + trend_rate * i for i in range(n - 1)]
    mids.append(base_price + trend_rate * (n - 1) + 2.0)  # jump clears the prior 20d high

    true_ranges = [1.0] * n
    for i in range(1, 40):
        true_ranges[i] = 5.0  # past high-ATR block sets the trailing-252d 90th percentile at 5.0

    volumes = [100_000.0] * n
    volumes[-1] = 2.0 * 100_000.0

    return [
        _scan_bar(d, m, tr, v)
        for d, m, tr, v in zip(dates, mids, true_ranges, volumes, strict=True)
    ]


def _clean_long_pullback_bars() -> list[setups.Bar]:
    """A minimal 44%-retracement bar series satisfying Setup-2 for a long pullback — same
    construction as test_setups.py's `_pullback_bars(0.44)` default, kept local for the
    same reason as `_clean_long_breakout_bars` above.
    """
    base_bar_count = 40
    pullback_days = 5
    entry_price = 1000.0
    extreme = 1050.0
    impulse_volume = 500_000.0
    pullback_volume = 100_000.0
    retracement_pct = 0.44

    dates = _scan_dates(base_bar_count + 1 + pullback_days)
    bars: list[setups.Bar] = []
    for i in range(base_bar_count):
        mid = 950.0 + (1000.0 - 950.0) * i / (base_bar_count - 1)
        bars.append(_scan_bar(dates[i], mid, 1.0, 100_000.0))

    bars.append(_scan_bar(dates[base_bar_count], 1045.0, 10.0, impulse_volume))

    target_close = extreme - retracement_pct * (extreme - entry_price)
    pullback_start = 1044.0
    for step in range(1, pullback_days + 1):
        mid = pullback_start + (target_close - pullback_start) * step / pullback_days
        bars.append(_scan_bar(dates[base_bar_count + step], mid, 1.0, pullback_volume))

    return bars


def test_scan_command_emits_alert_and_persists_state_on_breakout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    breakout_state_path = tmp_path / "breakout_state.json"
    client = _FakeScanClient({"ES": _clean_long_breakout_bars()})

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(breakout_state_path),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ALERT: ES setup=1 direction=long" in captured.out
    assert breakout_state_path.exists()
    persisted = json.loads(breakout_state_path.read_text(encoding="utf-8"))
    assert persisted["ES"]["direction"] == "long"

    # Alert must surface the actual computed stop/target, not just entry/atr14 — verified
    # via the real exits functions, never a hand-typed expected value.
    breakout_signal = setups.is_breakout(_clean_long_breakout_bars())
    assert breakout_signal is not None
    expected_stop = exits.compute_initial_stop(
        entry_price=breakout_signal.entry_price,
        atr14=breakout_signal.atr14,
        direction=breakout_signal.direction,
    )
    expected_target = exits.compute_target(
        entry_price=breakout_signal.entry_price,
        initial_stop=expected_stop,
        direction=breakout_signal.direction,
    )
    assert f"stop={expected_stop}" in captured.out
    assert f"target={expected_target}" in captured.out


def test_scan_command_emits_pullback_alert_when_prior_breakout_persisted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    breakout_state_path = tmp_path / "breakout_state.json"
    breakout_state_path.write_text(
        json.dumps({"ES": {"direction": "long", "entry_price": 1000.0, "atr14": 1.0}}),
        encoding="utf-8",
    )
    client = _FakeScanClient({"ES": _clean_long_pullback_bars()})

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(breakout_state_path),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ALERT: ES setup=2 direction=long" in captured.out


def test_scan_command_reports_no_signals_when_universe_quiet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    breakout_state_path = tmp_path / "breakout_state.json"
    client = _FakeScanClient({})  # every symbol -> [] -> ValueError caught, no signal

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(breakout_state_path),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No signals" in captured.out


# ─── scan -> journal wiring (REQ-015) — every scan must log a scan_log entry so
# reports._zero_signal_day_count() has real data to compute from, not silent always-zero ───


def test_scan_command_logs_no_signal_scan_to_journal(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    client = _FakeScanClient({})

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(journal_path),
        ],
        client_factory=lambda _path: client,
    )
    assert exit_code == 0

    scan_logs = [
        e for e in journal.read_all_entries(str(journal_path)) if e.entry_type == "scan_log"
    ]
    assert len(scan_logs) == 1
    assert scan_logs[0].signal_found is False


def test_scan_command_logs_signal_found_scan_to_journal(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    client = _FakeScanClient({"ES": _clean_long_breakout_bars()})

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(journal_path),
        ],
        client_factory=lambda _path: client,
    )
    assert exit_code == 0

    scan_logs = [
        e for e in journal.read_all_entries(str(journal_path)) if e.entry_type == "scan_log"
    ]
    assert len(scan_logs) == 1
    assert scan_logs[0].signal_found is True


def test_scan_command_suppressed_by_circuit_breaker_does_not_log_scan(tmp_path: Path) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"
    journal_path = tmp_path / "trade_journal.jsonl"
    flip_exit_code = cli.main(["circuit-breaker", "flip", "--state-path", str(state_path)])
    assert flip_exit_code == 0

    exit_code = cli.main(
        [
            "scan",
            "--circuit-breaker-path",
            str(state_path),
            "--journal-path",
            str(journal_path),
        ],
        client_factory=lambda _path: _FakeScanClient(),
    )
    assert exit_code == 0
    scan_logs = [
        e for e in journal.read_all_entries(str(journal_path)) if e.entry_type == "scan_log"
    ]
    assert scan_logs == []


def test_report_weekly_reflects_zero_signal_day_logged_by_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    client = _FakeScanClient({})

    scan_exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(journal_path),
        ],
        client_factory=lambda _path: client,
    )
    assert scan_exit_code == 0
    capsys.readouterr()  # discard scan's own stdout before checking the report's output

    today = date.today()
    report_exit_code = cli.main(
        [
            "report-weekly",
            "--start",
            today.isoformat(),
            "--end",
            today.isoformat(),
            "--journal-path",
            str(journal_path),
        ]
    )
    captured = capsys.readouterr()
    assert report_exit_code == 0
    assert "Zero-signal day count: 1" in captured.out


# ─── Client disconnect wiring — a real bug found only by running the CLI against a live
# Gateway: no command ever called client.disconnect(), leaking the connection until process
# exit and eventually causing "Socket disconnect" errors on later runs from the same client_id ──


def test_scan_command_disconnects_client_after_use(tmp_path: Path) -> None:
    client = _FakeScanClient()
    with patch.object(client, "disconnect") as mock_disconnect:
        cli.main(
            [
                "scan",
                "--breakout-state-path",
                str(tmp_path / "breakout_state.json"),
                "--journal-path",
                str(tmp_path / "trade_journal.jsonl"),
            ],
            client_factory=lambda _path: client,
        )
    mock_disconnect.assert_called_once()


def test_scan_command_disconnects_client_even_when_circuit_breaker_suppresses(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"
    cli.main(["circuit-breaker", "flip", "--state-path", str(state_path)])

    client = _FakeScanClient()
    with patch.object(client, "disconnect") as mock_disconnect:
        cli.main(
            ["scan", "--circuit-breaker-path", str(state_path)],
            client_factory=lambda _path: client,
        )
    mock_disconnect.assert_called_once()


def test_size_command_disconnects_client_after_fetching_net_liq(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _FakeScanClient(net_liq=100_000.0)
    with patch.object(client, "disconnect") as mock_disconnect:
        cli.main(
            ["size", "--stop-distance", "10", "--point-value", "50"],
            client_factory=lambda _path: client,
        )
    mock_disconnect.assert_called_once()


def test_review_positions_disconnects_client_after_use(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    client = _FakeScanClient()
    with patch.object(client, "disconnect") as mock_disconnect:
        cli.main(
            ["review-positions", "--journal-path", str(journal_path)],
            client_factory=lambda _path: client,
        )
    mock_disconnect.assert_called_once()


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


# ─── overtrading-status (REQ-012 wiring) — rolling calendar-month trade count via the real
# guardrails.count_trades_in_month()/check_overtrading(), not just the retroactive report ──


def test_overtrading_status_reports_count_under_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(_journal_add_base_args(journal_path))
    assert exit_code == 0

    status_exit_code = cli.main(["overtrading-status", "--journal-path", str(journal_path)])
    captured = capsys.readouterr()
    assert status_exit_code == 0
    assert "Trade count this month: 1" in captured.out


def test_overtrading_status_warns_when_over_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    trade_count = config.OVERTRADING_THRESHOLD_MIN + 1  # one over the lowest allowed threshold
    for _ in range(trade_count):
        exit_code = cli.main(_journal_add_base_args(journal_path))
        assert exit_code == 0

    status_exit_code = cli.main(
        [
            "overtrading-status",
            "--journal-path",
            str(journal_path),
            "--threshold",
            str(config.OVERTRADING_THRESHOLD_MIN),
        ]
    )
    captured = capsys.readouterr()
    assert status_exit_code == 0
    assert "Overtrading warning" in captured.out
    assert f"{trade_count} trade" in captured.out


def test_scan_command_proceeds_when_circuit_breaker_not_active(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "circuit_breaker_state.json"  # never flipped
    client = _FakeScanClient({})  # bare client with no market data — scan must still proceed

    exit_code = cli.main(
        [
            "scan",
            "--circuit-breaker-path",
            str(state_path),
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "circuit breaker" not in (captured.out + captured.err).lower()


# ─── review-positions (REQ-009 wiring) — open trades in the journal are checked against the
# real exits.check_time_stop() using market data from the connected client ──────────────────


def _flat_bars_after(entry_date: date, count: int) -> list[setups.Bar]:
    return [
        setups.Bar(
            date=(entry_date + timedelta(days=i)).isoformat(),
            open=1005.0,
            high=1006.0,
            low=1004.0,
            close=1005.0,
            volume=100_000.0,
        )
        for i in range(1, count + 1)
    ]


def test_review_positions_reports_no_open_positions_when_journal_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: _FakeScanClient(),
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No open positions" in captured.out


def test_review_positions_ignores_closed_trades(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main([*_journal_add_base_args(journal_path), "--realized-r", "1.5"])
    assert exit_code == 0

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: _FakeScanClient(),
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No open positions" in captured.out


# ─── journal-close (proper close mechanism, distinct from journal-add's one-shot
# --realized-r) — resolves a previously-opened trade by trade_id without counting as a new
# trade toward overtrading, and updates win-streak state exactly like journal-add's own
# --realized-r wiring does ──────────────────────────────────────────────────────────────────


def test_journal_add_prints_trade_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(_journal_add_base_args(journal_path))
    assert exit_code == 0
    captured = capsys.readouterr()

    entry = journal.read_all_entries(str(journal_path))[0]
    assert entry.trade_id is not None
    assert entry.trade_id in captured.out


def test_journal_close_resolves_a_previously_opened_trade(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(_journal_add_base_args(journal_path))
    assert exit_code == 0
    opened = journal.read_all_entries(str(journal_path))[0]
    assert opened.trade_id is not None

    exit_code = cli.main(
        [
            "journal-close",
            "--trade-id",
            opened.trade_id,
            "--realized-r",
            "1.5",
            "--reasoning",
            "hit target",
            "--journal-path",
            str(journal_path),
            "--win-streak-path",
            str(tmp_path / "win_streak_state.json"),
        ]
    )
    assert exit_code == 0

    entries = journal.read_all_entries(str(journal_path))
    assert len(entries) == 2
    close_entry = entries[1]
    assert close_entry.entry_type == "trade_close"
    assert close_entry.trade_id == opened.trade_id
    assert close_entry.realized_r == 1.5


def test_journal_close_rejects_unknown_trade_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            "journal-close",
            "--trade-id",
            "does-not-exist",
            "--realized-r",
            "1.0",
            "--reasoning",
            "n/a",
            "--journal-path",
            str(journal_path),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "no trade" in captured.err.lower() or "not found" in captured.err.lower()


def test_journal_close_rejects_already_closed_trade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    cli.main(_journal_add_base_args(journal_path))
    opened = journal.read_all_entries(str(journal_path))[0]
    assert opened.trade_id is not None

    close_args = [
        "journal-close",
        "--trade-id",
        opened.trade_id,
        "--realized-r",
        "1.0",
        "--reasoning",
        "closed",
        "--journal-path",
        str(journal_path),
        "--win-streak-path",
        str(tmp_path / "win_streak_state.json"),
    ]
    first_close = cli.main(close_args)
    assert first_close == 0

    second_close = cli.main(close_args)
    captured = capsys.readouterr()
    assert second_close != 0
    assert "already closed" in captured.err.lower()


def test_journal_close_updates_win_streak_state(tmp_path: Path) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    win_streak_path = tmp_path / "win_streak_state.json"

    trade_ids: list[str] = []
    for _ in range(config.WIN_STREAK_TRIGGER_COUNT):
        cli.main([*_journal_add_base_args(journal_path), "--win-streak-path", str(win_streak_path)])
        last_trade_id = journal.read_all_entries(str(journal_path))[-1].trade_id
        assert last_trade_id is not None
        trade_ids.append(last_trade_id)

    for trade_id in trade_ids:
        exit_code = cli.main(
            [
                "journal-close",
                "--trade-id",
                trade_id,
                "--realized-r",
                "1.0",
                "--reasoning",
                "hit target",
                "--journal-path",
                str(journal_path),
                "--win-streak-path",
                str(win_streak_path),
            ]
        )
        assert exit_code == 0

    state = guardrails.load_win_streak_state(str(win_streak_path))
    assert state.throttle_trades_remaining == config.WIN_STREAK_THROTTLE_TRADE_COUNT


def test_review_positions_treats_journal_close_as_resolved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    cli.main(_journal_add_base_args(journal_path))
    opened = journal.read_all_entries(str(journal_path))[0]
    assert opened.trade_id is not None

    cli.main(
        [
            "journal-close",
            "--trade-id",
            opened.trade_id,
            "--realized-r",
            "1.0",
            "--reasoning",
            "hit target",
            "--journal-path",
            str(journal_path),
            "--win-streak-path",
            str(tmp_path / "win_streak_state.json"),
        ]
    )

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: _FakeScanClient(),
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No open positions" in captured.out


def test_review_positions_flags_stale_position_past_time_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [*_journal_add_base_args(journal_path), "--entry-price", "1000", "--stop-price", "950"]
    )
    assert exit_code == 0

    entry_date = datetime.fromisoformat(
        journal.read_all_entries(str(journal_path))[0].timestamp
    ).date()
    # 15 daily bars of roughly flat price -> well past the 10-bar default time-stop, still
    # comfortably under 1R (50pt) of favorable movement
    client = _FakeScanClient({"ES": _flat_bars_after(entry_date, 15)})

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "FLAG: ES" in captured.out


def test_review_positions_does_not_flag_position_within_time_stop_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [*_journal_add_base_args(journal_path), "--entry-price", "1000", "--stop-price", "950"]
    )
    assert exit_code == 0

    entry_date = datetime.fromisoformat(
        journal.read_all_entries(str(journal_path))[0].timestamp
    ).date()
    # only 3 bars elapsed, under the 8-12 bar time-stop window regardless of config default
    client = _FakeScanClient({"ES": _flat_bars_after(entry_date, 3)})

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK: ES" in captured.out
    assert "FLAG" not in captured.out


def test_review_positions_reviews_stock_symbol_via_stock_bars(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main(
        [
            *_journal_add_base_args(journal_path),
            "--symbol",
            "AAPL",
            "--entry-price",
            "1000",
            "--stop-price",
            "950",
        ]
    )
    assert exit_code == 0

    entry_date = datetime.fromisoformat(
        journal.read_all_entries(str(journal_path))[0].timestamp
    ).date()
    # a non-futures symbol must be reviewed through historical_stock_bars, not
    # historical_futures_bars — 15 bars, well past the default time-stop
    client = _FakeScanClient(stock_bars_by_symbol={"AAPL": _flat_bars_after(entry_date, 15)})

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "FLAG: AAPL" in captured.out


def test_review_positions_reports_no_market_data_for_unrecognized_symbol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    journal_path = tmp_path / "trade_journal.jsonl"
    exit_code = cli.main([*_journal_add_base_args(journal_path), "--symbol", "ZZZZ"])
    assert exit_code == 0

    client = _FakeScanClient()  # no bars for ZZZZ under either futures or stock lookup

    exit_code = cli.main(
        ["review-positions", "--journal-path", str(journal_path)],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no market data available" in captured.out


# ─── Stock-universe live scanning (REQ-005 end-to-end) — live scanner symbols -> spread/ADV
# eligibility via the real universe.filter_stock_universe() -> setup detection -> alert ─────


def test_scan_command_emits_stock_alert_when_candidate_eligible_and_breaks_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _FakeScanClient(
        stock_symbols=["AAPL"],
        stock_bars_by_symbol={"AAPL": _clean_long_breakout_bars()},
        stock_spread_by_symbol={"AAPL": 0.0003},  # under STOCK_SPREAD_MAX_PCT (0.0005)
        stock_adv_by_symbol={"AAPL": 6_000_000.0},  # over STOCK_ADV_MIN_SHARES (5,000,000)
    )

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ALERT: AAPL setup=1 direction=long" in captured.out


def test_scan_command_excludes_stock_candidate_when_spread_too_wide(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _FakeScanClient(
        stock_symbols=["AAPL"],
        stock_bars_by_symbol={"AAPL": _clean_long_breakout_bars()},
        stock_spread_by_symbol={"AAPL": 0.0006},  # over STOCK_SPREAD_MAX_PCT (0.0005)
        stock_adv_by_symbol={"AAPL": 6_000_000.0},
    )

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AAPL" not in captured.out
    assert "No signals" in captured.out


def test_scan_command_excludes_stock_candidate_when_adv_too_low(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _FakeScanClient(
        stock_symbols=["AAPL"],
        stock_bars_by_symbol={"AAPL": _clean_long_breakout_bars()},
        stock_spread_by_symbol={"AAPL": 0.0003},
        stock_adv_by_symbol={"AAPL": 4_000_000.0},  # under STOCK_ADV_MIN_SHARES (5,000,000)
    )

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AAPL" not in captured.out
    assert "No signals" in captured.out


def test_scan_command_skips_stock_candidate_with_no_live_quote(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # AAPL is returned by the scanner but has no entry in stock_spread_by_symbol, so
    # stock_bid_ask_spread_pct raises ValueError -> the candidate is skipped, not fatal.
    client = _FakeScanClient(
        stock_symbols=["AAPL"],
        stock_bars_by_symbol={"AAPL": _clean_long_breakout_bars()},
        stock_adv_by_symbol={"AAPL": 6_000_000.0},
    )

    exit_code = cli.main(
        [
            "scan",
            "--breakout-state-path",
            str(tmp_path / "breakout_state.json"),
            "--journal-path",
            str(tmp_path / "trade_journal.jsonl"),
        ],
        client_factory=lambda _path: client,
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "No signals" in captured.out
