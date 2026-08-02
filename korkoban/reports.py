"""Weekly metrics report — reads the trade journal only through `journal.py`."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from korkoban import config, guardrails
from korkoban.journal import TradeJournalEntry

EXPECTANCY_WINDOW_TRADE_COUNT: int = 50


@dataclass(frozen=True)
class WeeklyReport:
    expectancy_r: float
    max_drawdown_r: float
    max_drawdown_pct: float
    forced_trade_count: int
    zero_signal_day_count: int


def _counted_trades_chronological(entries: list[TradeJournalEntry]) -> list[TradeJournalEntry]:
    trades = [e for e in entries if e.entry_type == "trade" and e.counted_in_stats is True]
    return sorted(trades, key=lambda e: e.timestamp)


def _expectancy_r(entries: list[TradeJournalEntry]) -> float:
    # "most recent" is judged over the whole journal, not clipped to the report window
    trades = _counted_trades_chronological(entries)
    window = trades[-EXPECTANCY_WINDOW_TRADE_COUNT:]
    if not window:
        return 0.0
    realized_rs = [t.realized_r for t in window if t.realized_r is not None]
    return sum(realized_rs) / len(realized_rs) if realized_rs else 0.0


def _max_drawdown(entries: list[TradeJournalEntry]) -> tuple[float, float]:
    trades = _counted_trades_chronological(entries)
    cumulative = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    max_drawdown_pct = 0.0
    for trade in trades:
        cumulative += trade.realized_r if trade.realized_r is not None else 0.0
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        if drawdown > max_drawdown_r:
            max_drawdown_r = drawdown
            # a zero/negative peak means no gain has ever been banked yet — report 0% rather
            # than dividing by zero
            max_drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0.0
    return max_drawdown_r, max_drawdown_pct


def _forced_trade_count(
    entries: list[TradeJournalEntry], start: date, end: date, threshold: int
) -> int:
    all_trades = sorted((e for e in entries if e.entry_type == "trade"), key=lambda e: e.timestamp)
    months: dict[tuple[int, int], list[TradeJournalEntry]] = {}
    for trade in all_trades:
        ts = datetime.fromisoformat(trade.timestamp)
        months.setdefault((ts.year, ts.month), []).append(trade)

    forced = 0
    for month_trades in months.values():
        for position, trade in enumerate(month_trades, start=1):
            if guardrails.check_overtrading(position, threshold=threshold):
                trade_date = datetime.fromisoformat(trade.timestamp).date()
                if start <= trade_date <= end:
                    forced += 1
    return forced


def _zero_signal_day_count(entries: list[TradeJournalEntry], start: date, end: date) -> int:
    scan_logs = [e for e in entries if e.entry_type == "scan_log"]
    days: dict[date, list[bool]] = {}
    for scan in scan_logs:
        day = datetime.fromisoformat(scan.timestamp).date()
        if start <= day <= end:
            days.setdefault(day, []).append(bool(scan.signal_found))
    return sum(1 for signals in days.values() if signals and not any(signals))


def compute_weekly_report(
    entries: list[TradeJournalEntry],
    start: date,
    end: date,
    overtrading_threshold: int = config.OVERTRADING_THRESHOLD_DEFAULT,
) -> WeeklyReport:
    max_drawdown_r, max_drawdown_pct = _max_drawdown(entries)
    return WeeklyReport(
        expectancy_r=_expectancy_r(entries),
        max_drawdown_r=max_drawdown_r,
        max_drawdown_pct=max_drawdown_pct,
        forced_trade_count=_forced_trade_count(entries, start, end, overtrading_threshold),
        zero_signal_day_count=_zero_signal_day_count(entries, start, end),
    )


def print_weekly_report(report: WeeklyReport) -> None:
    print(f"Expectancy (R): {report.expectancy_r}")
    print(f"Max drawdown (R): {report.max_drawdown_r}")
    print(f"Max drawdown (%): {report.max_drawdown_pct}")
    print(f"Forced trade count: {report.forced_trade_count}")
    print(f"Zero-signal day count: {report.zero_signal_day_count}")
