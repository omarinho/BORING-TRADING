"""CLI entrypoints: scan, size, journal-add, journal-eod-note, report-weekly.

The last module in korkoban/ — wires sizing/exits/universe/setups/journal/reports/
ibkr_client together behind `python -m korkoban.cli <command>`. Never imports ib_insync
directly; all IBKR access goes through `korkoban.ibkr_client.load_client`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast

from korkoban import config, exits, guardrails, journal, reports, setups, sizing, universe
from korkoban.guardrails import DEFAULT_CIRCUIT_BREAKER_STATE_PATH, DEFAULT_WIN_STREAK_STATE_PATH
from korkoban.journal import DEFAULT_JOURNAL_PATH, TradeJournalEntry

# Local structured-file persistence for the "last confirmed Setup 1 breakout per symbol"
# state — same JSON-file pattern as guardrails.py's CircuitBreakerState/WinStreakState — so
# a later scan can detect a Setup 2 pullback that follows a breakout confirmed on a prior day.
DEFAULT_BREAKOUT_STATE_PATH = "data/breakout_state.json"


class _ConnectedClient(Protocol):
    """Structural interface cli.py needs from a connected client — satisfied by the real
    IBKRClient's read-only methods and by test doubles alike. Used by scan, review-positions,
    and size (for its optional live Net Liquidation Value read)."""

    def historical_futures_bars(
        self, symbol: str, duration: str = "2 Y", bar_size: str = "1 day"
    ) -> list[setups.Bar]: ...

    def historical_stock_bars(
        self, symbol: str, duration: str = "2 Y", bar_size: str = "1 day"
    ) -> list[setups.Bar]: ...

    def stock_candidate_symbols(self) -> list[str]: ...

    def stock_bid_ask_spread_pct(self, symbol: str) -> float: ...

    def account_net_liquidation(self) -> float: ...

    def stock_average_daily_volume(self, symbol: str) -> float: ...

    def disconnect(self) -> None: ...


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="korkoban")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="Scan the universe for Setup 1 / Setup 2 signals"
    )
    scan_parser.add_argument("--ibkr-input", default="ibkr.input")
    scan_parser.add_argument("--circuit-breaker-path", default=DEFAULT_CIRCUIT_BREAKER_STATE_PATH)
    scan_parser.add_argument("--breakout-state-path", default=DEFAULT_BREAKOUT_STATE_PATH)
    scan_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)

    size_parser = subparsers.add_parser("size", help="Compute a position size")
    size_parser.add_argument(
        "--net-liq",
        type=float,
        default=None,
        help=(
            "Account Net Liquidation Value (REQ-006). If omitted, fetched live via "
            "IBKRClient.account_net_liquidation() (read-only account summary snapshot)."
        ),
    )
    size_parser.add_argument("--ibkr-input", default="ibkr.input")
    size_parser.add_argument("--stop-distance", type=float, required=True)
    size_parser.add_argument(
        "--point-value",
        type=float,
        default=None,
        help="Overrides --symbol's derived point value if both are given",
    )
    size_parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Derives point value via sizing.point_value_for() for a futures symbol, or 1.0 "
            "for anything else (stocks: 1 point = $1/share, per INSTRUCTIONS.md's sizing "
            "formula). Required unless --point-value is given directly."
        ),
    )
    size_parser.add_argument("--risk-pct", type=float, default=config.RISK_PCT_DEFAULT)
    size_parser.add_argument("--win-streak-path", default=DEFAULT_WIN_STREAK_STATE_PATH)

    add_parser = subparsers.add_parser("journal-add", help="Append a trade entry to the journal")
    add_parser.add_argument("--symbol", required=True)
    add_parser.add_argument("--direction", required=True, choices=["long", "short"])
    add_parser.add_argument("--setup", required=True)
    add_parser.add_argument("--entry-price", type=float, required=True)
    add_parser.add_argument("--stop-price", type=float, required=True)
    add_parser.add_argument("--target-price", type=float, required=True)
    add_parser.add_argument("--size", type=int, required=True)
    add_parser.add_argument("--risk-dollars", type=float, required=True)
    add_parser.add_argument("--realized-r", type=float, default=None)
    add_parser.add_argument("--checklist-gate-answer", required=True)
    add_parser.add_argument("--reasoning", required=True, help="Free-text rationale for the trade")
    add_parser.add_argument(
        "--screenshot-path", required=True, help="Path/reference to the entry screenshot"
    )
    add_parser.add_argument(
        "--with-management-plan",
        action="store_true",
        help=(
            "Compute the optional scale-50%%-at-1.8R / trail-remainder-at-1.5xATR management "
            "plan via exits.compute_management_plan() and attach it to the journal entry"
        ),
    )
    add_parser.add_argument(
        "--scale-out-r-multiple", type=float, default=config.SCALE_OUT_R_MULTIPLE
    )
    add_parser.add_argument("--trail-atr-multiple", type=float, default=config.TRAIL_ATR_MULTIPLE)
    add_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)
    add_parser.add_argument("--circuit-breaker-path", default=DEFAULT_CIRCUIT_BREAKER_STATE_PATH)
    add_parser.add_argument("--win-streak-path", default=DEFAULT_WIN_STREAK_STATE_PATH)

    eod_parser = subparsers.add_parser(
        "journal-eod-note", help="Append the one-per-day EOD emotional-state note"
    )
    eod_parser.add_argument("note")
    eod_parser.add_argument("--day", default=None, help="ISO date, defaults to today")
    eod_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)

    report_parser = subparsers.add_parser("report-weekly", help="Print the weekly metrics report")
    report_parser.add_argument("--start", required=True, help="ISO date")
    report_parser.add_argument("--end", required=True, help="ISO date")
    report_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)

    breaker_parser = subparsers.add_parser(
        "circuit-breaker", help="Flip or check the emotional circuit breaker (REQ-011)"
    )
    breaker_parser.add_argument("action", choices=["flip", "status"])
    breaker_parser.add_argument("--state-path", default=DEFAULT_CIRCUIT_BREAKER_STATE_PATH)

    win_streak_parser = subparsers.add_parser(
        "win-streak", help="Check the win-streak risk-throttle state (REQ-010)"
    )
    win_streak_parser.add_argument("action", choices=["status"])
    win_streak_parser.add_argument("--state-path", default=DEFAULT_WIN_STREAK_STATE_PATH)

    review_parser = subparsers.add_parser(
        "review-positions",
        help="Flag open trades that hit the time-stop without reaching 1R (REQ-009)",
    )
    review_parser.add_argument("--ibkr-input", default="ibkr.input")
    review_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)

    overtrading_parser = subparsers.add_parser(
        "overtrading-status",
        help="Check trade count in the current rolling calendar month (REQ-012)",
    )
    overtrading_parser.add_argument("--journal-path", default=DEFAULT_JOURNAL_PATH)
    overtrading_parser.add_argument(
        "--threshold", type=int, default=config.OVERTRADING_THRESHOLD_DEFAULT
    )

    return parser


def _resolve_point_value(args: argparse.Namespace) -> float | None:
    if args.point_value is not None:
        return float(args.point_value)
    if args.symbol is None:
        return None
    if args.symbol in config.FUTURES_POINT_VALUES:
        return sizing.point_value_for(args.symbol)
    return 1.0  # stocks: 1 point = $1/share, per INSTRUCTIONS.md's sizing formula


def _cmd_size(args: argparse.Namespace, client_factory: Callable[[str], object]) -> int:
    point_value = _resolve_point_value(args)
    if point_value is None:
        print("Either --point-value or --symbol is required.", file=sys.stderr)
        return 1

    if args.net_liq is not None:
        net_liq = float(args.net_liq)
    else:
        # REQ-006: capital base is account Net Liquidation Value from IBKR, not raw buying
        # power — fetched live only when --net-liq isn't given explicitly, so a caller who
        # already knows their NetLiq never has to connect to the Gateway just to size a trade.
        try:
            client = client_factory(args.ibkr_input)
        except ConnectionError as exc:
            print(f"Could not connect to IBKR Gateway: {exc}", file=sys.stderr)
            return 1
        connected_client = cast(_ConnectedClient, client)
        try:
            net_liq = connected_client.account_net_liquidation()
        finally:
            connected_client.disconnect()

    try:
        result = sizing.compute_size(
            net_liq=net_liq,
            stop_distance_points=args.stop_distance,
            point_value=point_value,
            risk_pct=args.risk_pct,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Win-streak throttle (REQ-010): after 3 consecutive winning trades, the next 12 trades'
    # sizing is automatically computed at a reduced risk_pct — never the raw --risk-pct verbatim.
    win_streak_state = guardrails.load_win_streak_state(args.win_streak_path)
    effective_risk_pct = guardrails.risk_pct_for_state(
        win_streak_state, base_risk_pct=args.risk_pct
    )
    if effective_risk_pct != args.risk_pct:
        print(
            f"win-streak throttle active: effective risk_pct={effective_risk_pct} "
            f"(base risk_pct={args.risk_pct}, {win_streak_state.throttle_trades_remaining} "
            "trade(s) remaining)"
        )
        # Bounds enforcement below only applies to raw user input (already validated above);
        # a guardrail-reduced value may legitimately fall below RISK_PCT_MIN.
        result = sizing.compute_size(
            net_liq=net_liq,
            stop_distance_points=args.stop_distance,
            point_value=point_value,
            risk_pct=effective_risk_pct,
            enforce_risk_pct_bounds=False,
        )

    print(
        f"units={result.units} risk_dollars={result.risk_dollars} "
        f"dollars_per_unit={result.dollars_per_unit}"
    )
    return 0


def _cmd_journal_add(args: argparse.Namespace) -> int:
    now = datetime.now()
    breaker_state = guardrails.load_circuit_breaker_state(args.circuit_breaker_path)
    if not guardrails.can_log_trade(breaker_state, now=now):
        assert breaker_state.paused_since is not None  # can_log_trade() False implies this
        resumes_at = breaker_state.paused_since + timedelta(days=config.EMOTIONAL_PAUSE_DAYS)
        print(
            "Cannot log trade: emotional circuit breaker is active until "
            f"{resumes_at.isoformat()} — no new trade may be logged as valid during the pause.",
            file=sys.stderr,
        )
        return 1

    management_plan = (
        exits.compute_management_plan(
            scale_out_r_multiple=args.scale_out_r_multiple,
            trail_atr_multiple=args.trail_atr_multiple,
        )
        if args.with_management_plan
        else None
    )

    entry = TradeJournalEntry(
        entry_type="trade",
        timestamp=now.isoformat(),
        symbol=args.symbol,
        direction=args.direction,
        setup=args.setup,
        entry_price=args.entry_price,
        stop_price=args.stop_price,
        target_price=args.target_price,
        size=args.size,
        risk_dollars=args.risk_dollars,
        realized_r=args.realized_r,
        checklist_gate_answer=args.checklist_gate_answer,
        reasoning=args.reasoning,
        screenshot_path=args.screenshot_path,
        scale_out_fraction=management_plan.scale_out_fraction if management_plan else None,
        scale_out_r_multiple=management_plan.scale_out_r_multiple if management_plan else None,
        trail_atr_multiple=management_plan.trail_atr_multiple if management_plan else None,
    )
    try:
        saved = journal.append_trade_entry(args.journal_path, entry)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Win-streak throttle (REQ-010): a trade's outcome becomes known exactly when --realized-r
    # is provided, so this is where the streak counter/throttle window advances and persists.
    if args.realized_r is not None:
        win_streak_state = guardrails.load_win_streak_state(args.win_streak_path)
        updated_win_streak_state = guardrails.update_win_streak_state(
            win_streak_state, realized_r=args.realized_r
        )
        guardrails.save_win_streak_state(args.win_streak_path, updated_win_streak_state)

    print(f"logged trade entry for {saved.symbol} (counted_in_stats={saved.counted_in_stats})")
    return 0


def _cmd_journal_eod_note(args: argparse.Namespace) -> int:
    day = date.fromisoformat(args.day) if args.day else date.today()
    try:
        journal.append_eod_note(args.journal_path, day, args.note)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"logged EOD note for {day.isoformat()}")
    return 0


def _cmd_report_weekly(args: argparse.Namespace) -> int:
    entries = journal.read_all_entries(args.journal_path)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    report = reports.compute_weekly_report(entries, start, end)
    reports.print_weekly_report(report)
    return 0


def _default_client_factory(path: str) -> object:
    # Local import — keeps ib_insync's dependency chain out of every command except `scan`.
    from korkoban.ibkr_client import load_client

    return load_client(path)


def _load_breakout_state(path: str) -> dict[str, setups.Setup1Signal]:
    """Reads the last confirmed Setup 1 breakout per symbol; a missing file means none yet."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with file_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {symbol: setups.Setup1Signal(**value) for symbol, value in raw.items()}


def _save_breakout_state(path: str, state: dict[str, setups.Setup1Signal]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as f:
        json.dump({symbol: asdict(signal) for symbol, signal in state.items()}, f)


_Alert = tuple[str, str, setups.Setup1Signal | setups.Setup2Signal]


def _scan_futures_universe(client: object, state: dict[str, setups.Setup1Signal]) -> list[_Alert]:
    """Fixed futures universe (REQ-002/003 end-to-end). `state` (last confirmed Setup 1
    breakout per symbol) is shared with `_scan_stock_universe` and persisted once by the
    caller — mutated in place here, not loaded/saved locally.
    """
    scan_client = cast(_ConnectedClient, client)
    alerts: list[_Alert] = []

    for symbol in universe.FUTURES_UNIVERSE:
        bars = scan_client.historical_futures_bars(symbol)
        try:
            breakout = setups.is_breakout(bars)
        except ValueError:
            # Insufficient trailing history for a fresh Setup-1 read on this symbol — Setup 2
            # has a lower data requirement (see setups.is_pullback), so still check it below
            # rather than skipping the symbol outright.
            breakout = None

        if breakout is not None:
            state[symbol] = breakout
            alerts.append((symbol, "1", breakout))
            continue

        pullback = setups.is_pullback(bars, state.get(symbol))
        if pullback is not None:
            alerts.append((symbol, "2", pullback))

    return alerts


def _stock_candidates(scan_client: _ConnectedClient) -> list[universe.StockCandidate]:
    """Builds StockCandidate rows from live scanner symbols + per-symbol spread/ADV reads.
    A symbol with no live quote or no volume history right now is skipped, not fatal — the
    scan still covers everything it can get real data for.
    """
    candidates: list[universe.StockCandidate] = []
    for symbol in scan_client.stock_candidate_symbols():
        try:
            spread_pct = scan_client.stock_bid_ask_spread_pct(symbol)
            avg_daily_volume = scan_client.stock_average_daily_volume(symbol)
        except ValueError:
            continue
        candidates.append(
            universe.StockCandidate(
                symbol=symbol,
                spread_pct=spread_pct,
                avg_daily_volume=avg_daily_volume,
                asset_class="stock",
            )
        )
    return candidates


def _scan_stock_universe(client: object, state: dict[str, setups.Setup1Signal]) -> list[_Alert]:
    """Live scanner candidates -> universe.filter_stock_universe() eligibility -> the same
    setup-detection loop as futures. `state` is shared with `_scan_futures_universe` (symbol
    strings don't collide across the two universes) and persisted once by the caller.
    """
    scan_client = cast(_ConnectedClient, client)
    alerts: list[_Alert] = []

    for candidate in universe.filter_stock_universe(_stock_candidates(scan_client)):
        bars = scan_client.historical_stock_bars(candidate.symbol)
        try:
            breakout = setups.is_breakout(bars)
        except ValueError:
            breakout = None

        if breakout is not None:
            state[candidate.symbol] = breakout
            alerts.append((candidate.symbol, "1", breakout))
            continue

        pullback = setups.is_pullback(bars, state.get(candidate.symbol))
        if pullback is not None:
            alerts.append((candidate.symbol, "2", pullback))

    return alerts


def _cmd_scan(args: argparse.Namespace, client_factory: Callable[[str], object]) -> int:
    try:
        client = client_factory(args.ibkr_input)
    except ConnectionError as exc:
        print(f"Could not connect to IBKR Gateway: {exc}", file=sys.stderr)
        return 1

    try:
        breaker_state = guardrails.load_circuit_breaker_state(args.circuit_breaker_path)
        if not guardrails.can_alert(breaker_state, now=datetime.now()):
            assert breaker_state.paused_since is not None  # can_alert() False implies this
            resumes_at = breaker_state.paused_since + timedelta(days=config.EMOTIONAL_PAUSE_DAYS)
            print(
                "Alerts suppressed: emotional circuit breaker is active until "
                f"{resumes_at.isoformat()} — no new setup alert will be surfaced during "
                "the pause."
            )
            return 0

        breakout_state = _load_breakout_state(args.breakout_state_path)
        alerts = _scan_futures_universe(client, breakout_state) + _scan_stock_universe(
            client, breakout_state
        )
        _save_breakout_state(args.breakout_state_path, breakout_state)

        # REQ-015: every completed scan is logged so reports._zero_signal_day_count() has
        # real data — a scan suppressed by the circuit breaker above never reaches this
        # line, since the system isn't actually looking for signals during a pause.
        journal.append_scan_log(
            args.journal_path, timestamp=datetime.now(), signal_found=bool(alerts)
        )

        if not alerts:
            print("No signals — 0 candidates matched Setup 1 or Setup 2 this scan.")
            return 0

        for symbol, setup_id, signal in alerts:
            stop = exits.compute_initial_stop(
                entry_price=signal.entry_price, atr14=signal.atr14, direction=signal.direction
            )
            target = exits.compute_target(
                entry_price=signal.entry_price, initial_stop=stop, direction=signal.direction
            )
            print(
                f"ALERT: {symbol} setup={setup_id} direction={signal.direction} "
                f"entry={signal.entry_price} atr14={signal.atr14} stop={stop} target={target}"
            )
        return 0
    finally:
        cast(_ConnectedClient, client).disconnect()


def _cmd_circuit_breaker(args: argparse.Namespace) -> int:
    now = datetime.now()
    state = guardrails.load_circuit_breaker_state(args.state_path)
    if args.action == "flip":
        new_state = guardrails.flip_circuit_breaker(state, now=now)
        guardrails.save_circuit_breaker_state(args.state_path, new_state)
        if new_state.paused_since == now:
            print(
                f"Circuit breaker activated at {now.isoformat()}; new alerts suppressed and "
                f"new trade logging blocked for {config.EMOTIONAL_PAUSE_DAYS} calendar days."
            )
        else:
            assert new_state.paused_since is not None
            print(
                "Circuit breaker already active since "
                f"{new_state.paused_since.isoformat()}; re-flipping does not shorten it."
            )
        return 0
    # action == "status"
    if guardrails.is_paused(state, now=now):
        assert state.paused_since is not None
        print(f"Circuit breaker ACTIVE since {state.paused_since.isoformat()}")
    else:
        print("Circuit breaker inactive")
    return 0


def _cmd_win_streak(args: argparse.Namespace) -> int:
    # action == "status" (only supported action)
    state = guardrails.load_win_streak_state(args.state_path)
    if state.throttle_trades_remaining > 0:
        effective_risk_pct = guardrails.risk_pct_for_state(
            state, base_risk_pct=config.RISK_PCT_DEFAULT
        )
        print(
            f"Win-streak throttle ACTIVE: {state.throttle_trades_remaining} trade(s) remaining "
            f"at reduced risk_pct={effective_risk_pct} (base risk_pct={config.RISK_PCT_DEFAULT})"
        )
    else:
        print(f"Win-streak throttle inactive (consecutive_wins={state.consecutive_wins})")
    return 0


def _cmd_review_positions(args: argparse.Namespace, client_factory: Callable[[str], object]) -> int:
    try:
        client = client_factory(args.ibkr_input)
    except ConnectionError as exc:
        print(f"Could not connect to IBKR Gateway: {exc}", file=sys.stderr)
        return 1
    scan_client = cast(_ConnectedClient, client)

    try:
        open_trades = [
            entry
            for entry in journal.read_all_entries(args.journal_path)
            if entry.entry_type == "trade" and entry.realized_r is None
        ]
        if not open_trades:
            print("No open positions to review.")
            return 0

        for entry in open_trades:
            assert entry.symbol is not None
            assert entry.entry_price is not None
            assert entry.stop_price is not None
            assert entry.direction is not None

            bars = (
                scan_client.historical_futures_bars(entry.symbol)
                if entry.symbol in universe.FUTURES_UNIVERSE
                else scan_client.historical_stock_bars(entry.symbol)
            )
            if not bars:
                print(f"{entry.symbol}: no market data available, skipping time-stop check.")
                continue

            entry_date = datetime.fromisoformat(entry.timestamp).date()
            bars_since_entry = sum(1 for bar in bars if date.fromisoformat(bar.date) > entry_date)
            initial_risk = abs(entry.entry_price - entry.stop_price)
            current_close = bars[-1].close
            r_now = (
                (current_close - entry.entry_price) / initial_risk
                if entry.direction == "long"
                else (entry.entry_price - current_close) / initial_risk
            )

            if exits.check_time_stop(bars_since_entry=bars_since_entry, realized_r=r_now):
                print(
                    f"FLAG: {entry.symbol} entered {entry.timestamp} — {bars_since_entry} "
                    f"bar(s) elapsed without reaching 1R (currently {r_now:.2f}R) — flag "
                    "for manual closure review."
                )
            else:
                print(
                    f"OK: {entry.symbol} entered {entry.timestamp} — {bars_since_entry} "
                    f"bar(s) elapsed, currently {r_now:.2f}R."
                )
        return 0
    finally:
        scan_client.disconnect()


def _cmd_overtrading_status(args: argparse.Namespace) -> int:
    now = datetime.now()
    trade_timestamps = [
        datetime.fromisoformat(entry.timestamp)
        for entry in journal.read_all_entries(args.journal_path)
        if entry.entry_type == "trade"
    ]
    count = guardrails.count_trades_in_month(trade_timestamps, year=now.year, month=now.month)

    if guardrails.check_overtrading(count, threshold=args.threshold):
        print(
            f"Overtrading warning: {count} trade(s) logged this month, over the threshold of "
            f"{args.threshold} — flagged only, the human still executes every trade manually."
        )
    else:
        print(f"Trade count this month: {count} (threshold {args.threshold})")
    return 0


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[str], object] = _default_client_factory,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args, client_factory)
    if args.command == "size":
        return _cmd_size(args, client_factory)
    if args.command == "journal-add":
        return _cmd_journal_add(args)
    if args.command == "journal-eod-note":
        return _cmd_journal_eod_note(args)
    if args.command == "report-weekly":
        return _cmd_report_weekly(args)
    if args.command == "circuit-breaker":
        return _cmd_circuit_breaker(args)
    if args.command == "win-streak":
        return _cmd_win_streak(args)
    if args.command == "review-positions":
        return _cmd_review_positions(args, client_factory)
    if args.command == "overtrading-status":
        return _cmd_overtrading_status(args)
    raise AssertionError(f"unhandled command {args.command!r}")  # unreachable — argparse validates


if __name__ == "__main__":
    sys.exit(main())
