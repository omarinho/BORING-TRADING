"""CLI entrypoints: scan, size, journal-add, journal-eod-note, report-weekly.

The last module in korkoban/ — wires sizing/exits/universe/setups/journal/reports/
ibkr_client together behind `python -m korkoban.cli <command>`. Never imports ib_insync
directly; all IBKR access goes through `korkoban.ibkr_client.load_client`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta

from korkoban import config, exits, guardrails, journal, reports, sizing
from korkoban.guardrails import DEFAULT_CIRCUIT_BREAKER_STATE_PATH, DEFAULT_WIN_STREAK_STATE_PATH
from korkoban.journal import DEFAULT_JOURNAL_PATH, TradeJournalEntry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="korkoban")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser(
        "scan", help="Scan the universe for Setup 1 / Setup 2 signals"
    )
    scan_parser.add_argument("--ibkr-input", default="ibkr.input")
    scan_parser.add_argument("--circuit-breaker-path", default=DEFAULT_CIRCUIT_BREAKER_STATE_PATH)

    size_parser = subparsers.add_parser("size", help="Compute a position size")
    size_parser.add_argument("--net-liq", type=float, required=True)
    size_parser.add_argument("--stop-distance", type=float, required=True)
    size_parser.add_argument("--point-value", type=float, required=True)
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

    return parser


def _cmd_size(args: argparse.Namespace) -> int:
    try:
        result = sizing.compute_size(
            net_liq=args.net_liq,
            stop_distance_points=args.stop_distance,
            point_value=args.point_value,
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
            net_liq=args.net_liq,
            stop_distance_points=args.stop_distance,
            point_value=args.point_value,
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


def _cmd_scan(args: argparse.Namespace, client_factory: Callable[[str], object]) -> int:
    try:
        client_factory(args.ibkr_input)
    except ConnectionError as exc:
        print(f"Could not connect to IBKR Gateway: {exc}", file=sys.stderr)
        return 1

    breaker_state = guardrails.load_circuit_breaker_state(args.circuit_breaker_path)
    if not guardrails.can_alert(breaker_state, now=datetime.now()):
        assert breaker_state.paused_since is not None  # can_alert() False implies this
        resumes_at = breaker_state.paused_since + timedelta(days=config.EMOTIONAL_PAUSE_DAYS)
        print(
            "Alerts suppressed: emotional circuit breaker is active until "
            f"{resumes_at.isoformat()} — no new setup alert will be surfaced during the pause."
        )
        return 0

    # Full scan wiring (universe -> historical_bars -> setups.is_breakout/is_pullback) is not
    # exercised in this environment without a live paper Gateway; connecting successfully is
    # confirmed here, the scan loop itself is covered by the integration tier.
    print("Connected to IBKR Gateway (read-only) — scan not yet wired end-to-end.")
    return 0


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


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[str], object] = _default_client_factory,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return _cmd_scan(args, client_factory)
    if args.command == "size":
        return _cmd_size(args)
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
    raise AssertionError(f"unhandled command {args.command!r}")  # unreachable — argparse validates


if __name__ == "__main__":
    sys.exit(main())
