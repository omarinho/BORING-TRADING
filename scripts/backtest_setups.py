"""Walk-forward historical check for Setup 1 / Setup 2: how often would they have fired?

Read-only diagnostic, not part of the korkoban package (tests/unit/test_package_layout.py
pins the exact module set inside korkoban/, so this lives outside it). Pulls historical daily
bars over IBKR's read-only API and replays setups.is_breakout / setups.is_pullback day by day,
exactly the way `korkoban.cli scan` evaluates one live day — just looped over history instead
of stopping at the most recent bar. Answers "is 0 signals today expected, or is something
broken?" with a base rate instead of a guess.

Defaults to the fixed futures universe (config.FUTURES_SYMBOLS). Can also check individual
stock symbols via --asset-class stock — the Setup 1/2 math itself is the same pure function of
OHLCV bars either way. What can't be backtested is the *daily scanner eligibility* for stocks
(IBKR's live TOP_PERC_GAIN result has no historical equivalent to replay) — so a stock run here
answers "how often would Setup 1/2 have fired on this symbol's own history", not "how often
would this symbol have been in the scanner's candidate list that day".

Usage:
    .venv/Scripts/python.exe scripts/backtest_setups.py
    .venv/Scripts/python.exe scripts/backtest_setups.py --duration "10 Y" --symbols ES,NQ
    .venv/Scripts/python.exe scripts/backtest_setups.py --asset-class stock --symbols PLTR
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from korkoban import config, ibkr_client, setups  # noqa: E402


def _min_required_bars() -> int:
    return config.ATR_PERIOD + config.ATR_PERCENTILE_WINDOW_DAYS + 1


_Setup1Hits = list[tuple[str, setups.Setup1Signal]]
_Setup2Hits = list[tuple[str, setups.Setup2Signal]]


def backtest_symbol(symbol: str, bars: list[setups.Bar]) -> tuple[_Setup1Hits, _Setup2Hits]:
    """Replays one symbol's bar history day by day, mirroring cli.py's live scan logic:
    a Setup 1 hit on a given day updates the tracked breakout state and is not also checked
    for Setup 2 that same day; otherwise Setup 2 is checked against the last confirmed
    breakout, if any. Uses the same per-symbol volume-ratio override cli.py's scan applies.
    """
    min_required = _min_required_bars()
    setup1_hits: _Setup1Hits = []
    setup2_hits: _Setup2Hits = []
    last_breakout: setups.Setup1Signal | None = None
    volume_ratio_multiple = config.volume_ratio_multiple_for(symbol)

    for end in range(min_required, len(bars) + 1):
        window = bars[:end]
        today = window[-1]

        breakout = setups.is_breakout(window, volume_ratio_multiple=volume_ratio_multiple)
        if breakout is not None:
            last_breakout = breakout
            setup1_hits.append((today.date, breakout))
            continue

        pullback = setups.is_pullback(window, last_breakout)
        if pullback is not None:
            setup2_hits.append((today.date, pullback))

    return setup1_hits, setup2_hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default=",".join(config.FUTURES_SYMBOLS),
        help=f"Comma-separated symbols (default: {','.join(config.FUTURES_SYMBOLS)})",
    )
    parser.add_argument(
        "--asset-class",
        choices=("futures", "stock"),
        default="futures",
        help="Which historical-bars source to use (default: futures)",
    )
    parser.add_argument(
        "--duration", default="5 Y", help="IBKR historical duration string (default: '5 Y')"
    )
    parser.add_argument(
        "--ibkr-input", default="ibkr.input", help="Path to IBKR connection config"
    )
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    min_required = _min_required_bars()

    try:
        client = ibkr_client.load_client(args.ibkr_input)
    except ConnectionError as exc:
        print(f"Could not connect to IBKR Gateway: {exc}", file=sys.stderr)
        return 1

    total_evaluable_days = 0
    total_setup1 = 0
    total_setup2 = 0

    print(f"Backtesting Setup 1 / Setup 2 over {args.duration} of daily bars")
    print(f"(minimum history required before the first evaluable day: {min_required} bars)\n")

    try:
        for symbol in symbols:
            bars = (
                client.historical_futures_bars(symbol, duration=args.duration)
                if args.asset_class == "futures"
                else client.historical_stock_bars(symbol, duration=args.duration)
            )
            evaluable_days = max(0, len(bars) - min_required + 1)
            total_evaluable_days += evaluable_days

            if evaluable_days == 0:
                print(f"{symbol}: {len(bars)} bars — not enough history to evaluate even once")
                continue

            setup1_hits, setup2_hits = backtest_symbol(symbol, bars)
            total_setup1 += len(setup1_hits)
            total_setup2 += len(setup2_hits)

            print(f"{symbol}: {len(bars)} bars, {evaluable_days} evaluable days")
            if setup1_hits:
                print("  Setup 1:")
                for date, s1_signal in setup1_hits:
                    print(f"    {date}  {s1_signal.direction:<5}  entry={s1_signal.entry_price}")
            else:
                print("  Setup 1: none")
            if setup2_hits:
                print("  Setup 2:")
                for date, s2_signal in setup2_hits:
                    print(f"    {date}  {s2_signal.direction:<5}  entry={s2_signal.entry_price}")
            else:
                print("  Setup 2: none")
            print()
    finally:
        client.disconnect()

    symbol_days = total_evaluable_days
    print("-" * 60)
    print(f"TOTAL: {symbol_days} symbol-days evaluated across {len(symbols)} symbols")
    if symbol_days:
        print(
            f"  Setup 1 signals: {total_setup1}"
            + (f"  (1 every ~{symbol_days // total_setup1} symbol-days)" if total_setup1 else "")
        )
        print(
            f"  Setup 2 signals: {total_setup2}"
            + (f"  (1 every ~{symbol_days // total_setup2} symbol-days)" if total_setup2 else "")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
