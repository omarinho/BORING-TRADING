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


def _resolved_trades_chronological(entries: list[TradeJournalEntry]) -> list[tuple[str, float]]:
    """(timestamp, realized_r) for every counted, resolved trade — whether resolved in one
    shot (realized_r already on the opening "trade" entry) or via a separate "trade_close"
    entry referencing the same trade_id (see journal.append_trade_close). Ordered by
    resolution time. A "trade_close" is never itself a trade — it resolves one.
    """
    opens_by_id = {
        e.trade_id: e for e in entries if e.entry_type == "trade" and e.trade_id is not None
    }
    resolved: list[tuple[str, float]] = []

    for e in entries:
        if e.entry_type == "trade" and e.realized_r is not None and e.counted_in_stats is True:
            resolved.append((e.timestamp, e.realized_r))

    for e in entries:
        if e.entry_type != "trade_close" or e.realized_r is None or e.trade_id is None:
            continue
        open_entry = opens_by_id.get(e.trade_id)
        if open_entry is None or open_entry.realized_r is not None:
            continue  # unknown trade_id, or already resolved at open — avoid double counting
        if open_entry.counted_in_stats is True:
            resolved.append((e.timestamp, e.realized_r))

    return sorted(resolved, key=lambda t: t[0])


def _expectancy_r(entries: list[TradeJournalEntry]) -> float:
    # "most recent" is judged over the whole journal, not clipped to the report window
    resolved = _resolved_trades_chronological(entries)
    window = resolved[-EXPECTANCY_WINDOW_TRADE_COUNT:]
    if not window:
        return 0.0
    return sum(r for _, r in window) / len(window)


def _max_drawdown(entries: list[TradeJournalEntry]) -> tuple[float, float]:
    resolved = _resolved_trades_chronological(entries)
    cumulative = 0.0
    peak = 0.0
    max_drawdown_r = 0.0
    max_drawdown_pct = 0.0
    for _, realized_r in resolved:
        cumulative += realized_r
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
