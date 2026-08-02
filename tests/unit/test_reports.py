# REQ-013, REQ-015
from __future__ import annotations

from datetime import date

import pytest

from korkoban.journal import TradeJournalEntry
from korkoban.reports import WeeklyReport, compute_weekly_report, print_weekly_report


def _trade(
    day: int, month: int = 1, year: int = 2026, hour: int = 10, realized_r: float = 1.0,
    counted_in_stats: bool = True,
) -> TradeJournalEntry:
    return TradeJournalEntry(
        entry_type="trade",
        timestamp=f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00",
        symbol="ES",
        realized_r=realized_r,
        checklist_gate_answer="edge_based" if counted_in_stats else "impulse",
        counted_in_stats=counted_in_stats,
    )


def _scan(
    day: int, hour: int, signal_found: bool, month: int = 1, year: int = 2026
) -> TradeJournalEntry:
    return TradeJournalEntry(
        entry_type="scan_log",
        timestamp=f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00",
        signal_found=signal_found,
    )


def test_tc_013_04_expectancy_excludes_counted_in_stats_false_entries() -> None:
    entries = [
        _trade(1, realized_r=1.0, counted_in_stats=True),
        _trade(2, realized_r=2.0, counted_in_stats=True),
        _trade(3, realized_r=3.0, counted_in_stats=True),
        _trade(4, realized_r=100.0, counted_in_stats=False),  # would skew the mean if included
    ]
    report = compute_weekly_report(entries, start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert report.expectancy_r == pytest.approx(2.0)


def test_tc_015_01_expectancy_averages_only_most_recent_fifty_counted_trades() -> None:
    old_outlier_trades = [_trade(day=i + 1, month=1, realized_r=100.0) for i in range(10)]
    recent_trades = [_trade(day=i + 1, month=2, realized_r=1.0) for i in range(28)] + [
        _trade(day=i + 1, month=3, realized_r=1.0) for i in range(22)
    ]
    entries = old_outlier_trades + recent_trades  # 10 old outliers + 50 recent
    report = compute_weekly_report(entries, start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert report.expectancy_r == pytest.approx(1.0)


def test_tc_015_02_max_drawdown_computed_correctly_for_known_sequence() -> None:
    # cumulative R: 2, 1, 4, 0, 1 -> running peak: 2, 2, 4, 4, 4 -> drawdown: 0, 1, 0, 4, 3
    realized_rs = [2.0, -1.0, 3.0, -4.0, 1.0]
    entries = [_trade(day=i + 1, realized_r=r) for i, r in enumerate(realized_rs)]
    report = compute_weekly_report(entries, start=date(2026, 1, 1), end=date(2026, 1, 31))
    assert report.max_drawdown_r == pytest.approx(4.0)
    assert report.max_drawdown_pct == pytest.approx(100.0)


def test_tc_015_03_forced_trade_count_scoped_to_requested_range() -> None:
    # 17 trades in January 2026 (one per day), default threshold=15 -> trades #16 and #17
    # in the month are "forced"; restrict the range to exclude day 17 so only #16 counts.
    entries = [_trade(day=d) for d in range(1, 18)]
    report = compute_weekly_report(entries, start=date(2026, 1, 1), end=date(2026, 1, 16))
    assert report.forced_trade_count == 1


def test_tc_015_04_zero_signal_day_count_scoped_to_requested_range() -> None:
    entries = [
        _scan(day=1, hour=10, signal_found=False),
        _scan(day=1, hour=15, signal_found=False),  # day 1: all False -> zero-signal day
        _scan(day=2, hour=10, signal_found=True),
        _scan(day=2, hour=15, signal_found=False),  # day 2: mixed -> not a zero-signal day
        _scan(day=3, hour=10, signal_found=False),  # day 3: all False, but outside range
    ]
    report = compute_weekly_report(entries, start=date(2026, 1, 1), end=date(2026, 1, 2))
    assert report.zero_signal_day_count == 1


def test_tc_015_05_print_weekly_report_prints_all_four_figures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = WeeklyReport(
        expectancy_r=1.25,
        max_drawdown_r=3.5,
        max_drawdown_pct=42.0,
        forced_trade_count=2,
        zero_signal_day_count=4,
    )
    print_weekly_report(report)
    out = capsys.readouterr().out
    assert "1.25" in out
    assert "3.5" in out
    assert "42.0" in out
    assert "2" in out
    assert "4" in out
