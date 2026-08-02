# BORING-TRADING — KORKOBAN

A boring, rule-based, edge-only swing-trading scanner and trade journal for Interactive
Brokers (IBKR). No discretion, no LLM/AI component, no order placement — KORKOBAN reads
market data and account state through a **read-only** IBKR connection, detects two fixed
setups, sizes and journals trades, and prints weekly metrics. It never places, modifies, or
cancels an order.

## Requirements

- Python 3.13
- An existing virtual environment at `.venv/` (this project never creates a second one)
- IBKR TWS or IB Gateway, **paper trading account**, with **Read-Only API enabled**
  (only required for the integration test tier and for live scanning — the unit test tier
  runs fully offline with zero network dependency)

## Setup

```bash
.venv/Scripts/python.exe -m pip install -e .[dev]
```

### IBKR connection (`ibkr.input`)

Connection parameters (`host`, `port`, `client_id`) are never hardcoded — they are read at
runtime from a local `ibkr.input` file (gitignored). Copy the committed template and adjust:

```bash
cp ibkr.input.example ibkr.input
```

```
host=127.0.0.1
port=4002
client_id=17
```

**Before running the integration test tier or the live scanner, enable Read-Only API:**
TWS/Gateway → *Configure* → *API* → *Settings* → check **"Read-Only API"**. KORKOBAN's
`ibkr_client.py` connects with `readonly=True` and exposes only market-data and
account-summary read methods (`historical_bars`, `account_net_liquidation`,
`stock_candidate_scan`) — no method in this codebase can submit, modify, or cancel an order.

## Running tests

Two tiers, run separately, never merged:

```bash
# Unit tier — pure logic, synthetic OHLCV fixtures, zero network dependency
.venv/Scripts/python.exe -m pytest -v -m "not integration"

# Integration tier — requires a running paper Gateway with Read-Only API enabled
.venv/Scripts/python.exe -m pytest -v -m integration
```

## Lint / format / typecheck

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m black .
.venv/Scripts/python.exe -m mypy .
```

## CLI usage

```bash
.venv/Scripts/python.exe -m korkoban.cli scan
.venv/Scripts/python.exe -m korkoban.cli size --stop-distance 10 --symbol ES  # NetLiq fetched live
.venv/Scripts/python.exe -m korkoban.cli journal-add \
  --symbol ES --direction long --setup 1 \
  --entry-price 5100 --stop-price 5085 --target-price 5137.5 \
  --size 2 --risk-dollars 500 \
  --checklist-gate-answer edge_based \
  --reasoning "clean 20d breakout, volume 2.1x, matches the edge" \
  --screenshot-path screenshots/es_20260802.png
  # --checklist-gate-answer must be "edge_based" or "impulse" — anything else is rejected;
  # "impulse" is still logged but excluded from win-rate/expectancy stats (the checklist gate)
  # prints trade_id=<uuid> — save it, you need it to close the trade later
.venv/Scripts/python.exe -m korkoban.cli journal-close \
  --trade-id <uuid from journal-add> --realized-r 2.0 --reasoning "hit target"
.venv/Scripts/python.exe -m korkoban.cli journal-eod-note "felt disciplined today"
.venv/Scripts/python.exe -m korkoban.cli report-weekly --start 2026-07-27 --end 2026-08-02
.venv/Scripts/python.exe -m korkoban.cli review-positions
.venv/Scripts/python.exe -m korkoban.cli circuit-breaker status
.venv/Scripts/python.exe -m korkoban.cli win-streak status
.venv/Scripts/python.exe -m korkoban.cli overtrading-status
```

(Also installable as a console script: `korkoban scan`, once `pip install -e .` has been run.)

### `scan` — what it actually does

`scan` connects to the Gateway (read-only), checks the emotional circuit breaker, then scans
the full instrument universe for Setup 1 (breakout) and Setup 2 (pullback) signals and prints
an `ALERT: <symbol> setup=<1|2> direction=... entry=... atr14=... stop=... target=...` line per
match (or "No signals" if the universe is quiet — expected most days), with `stop`/`target`
computed for real via `exits.compute_initial_stop`/`compute_target`, not just the raw signal.

- **Futures** (ES, NQ, YM, RTY, GC, CL): ~2 years of daily bars per symbol via
  `IBKRClient.historical_futures_bars`.
- **Stocks**: `IBKRClient.stock_candidate_symbols()` pulls live scanner candidates, each is
  read for a live bid/ask spread (`stock_bid_ask_spread_pct`) and 50-day average volume
  (`stock_average_daily_volume`) — a candidate with no live quote or no volume history right
  now is skipped, not fatal. Candidates are filtered through the real
  `universe.filter_stock_universe()` (spread < 0.05%, ADV > 5,000,000 shares), and only
  eligible symbols get a `historical_stock_bars` pull + setup-detection pass.

The last confirmed Setup 1 breakout per symbol (futures and stocks share the same state,
keyed by symbol) is persisted to `data/breakout_state.json` (gitignored) so a later scan can
still detect a Setup 2 pullback that follows a breakout confirmed on a prior day. Every
completed scan also logs a `scan_log` entry to the trade journal (`signal_found` true/false)
so `report-weekly`'s "zero-signal day count" reflects real scan history instead of always
reading 0 — a scan suppressed by the circuit breaker is not logged, since the system isn't
actually looking for signals during a pause.

### `journal-add` / `journal-close` — opening and closing a trade are two different events

`journal-add` opens a trade and assigns it a unique `trade_id` (printed in the confirmation
line — save it). `review-positions` treats that trade as open until it's explicitly resolved.

**Resolving it is `journal-close --trade-id <id> --realized-r <R> --reasoning <why>`, not a
second `journal-add` call.** The journal is append-only, so there's no way to edit the
original entry — but logging a second full `journal-add` for the same position would create
an entirely new, unrelated `"trade"` record, which **counts as a second trade toward
`overtrading-status`/`report-weekly`'s forced-trade-count**, even though you only ever opened
one position. `journal-close` appends a `"trade_close"` entry referencing the same `trade_id`
instead — it resolves the open position (removes it from `review-positions`, feeds
`realized_r` into expectancy/drawdown, updates the win-streak throttle) without ever counting
as a trade of its own.

(`journal-add --realized-r <R>` directly, in one shot, is still supported — for logging a
trade you already know the outcome of, e.g. backfilling history. That path never needs
`journal-close`, since it isn't "open" to begin with.)

### `review-positions` — time-stop enforcement (REQ-009)

Reads every open trade from the journal (`realized_r` not yet set), pulls each symbol's
latest daily bars, and calls `exits.check_time_stop()` with the real bars-elapsed-since-entry
count and the position's current unrealized R. Prints `FLAG: <symbol> ...` for any position
that has gone `TIME_STOP_BARS_DEFAULT` (10) bars without reaching 1R — the system does not
auto-close it, only surfaces it for manual review, per INSTRUCTIONS.md. Covers both futures
and stock positions — a symbol in the fixed futures universe is read via
`historical_futures_bars`, anything else via `historical_stock_bars`.

### `size` — position sizing (REQ-006)

`--net-liq` is optional: if omitted, it's fetched live via `IBKRClient.account_net_liquidation()`
(read-only account summary snapshot) rather than typed in by hand — pass `--net-liq` explicitly
to skip connecting to the Gateway entirely. `--point-value` is similarly optional when `--symbol`
is given: a recognized futures symbol resolves via `sizing.point_value_for()`
(`config.FUTURES_POINT_VALUES`); anything else resolves to `1.0` (stocks: 1 point = $1/share,
per INSTRUCTIONS.md's sizing formula). `--point-value` always overrides the derived value if
both are given. The win-streak throttle (REQ-010) is applied automatically on top of either path.

### `overtrading-status` (REQ-012)

Prints the trade count logged in the current rolling calendar month against a configurable
threshold (`config.OVERTRADING_THRESHOLD_DEFAULT`, bounded to `[12, 15]`) via the real
`guardrails.count_trades_in_month()`/`check_overtrading()`. This is a live check, independent
of `report-weekly`'s retroactive `forced_trade_count` metric — it never blocks trading, only
flags it, since the human always executes manually.

## Package layout

```
korkoban/
  config.py        # every tunable threshold, one place — no magic numbers elsewhere
  ibkr_client.py    # the ONLY module that imports ib_insync's IB object; read-only
  universe.py       # fixed futures universe + dynamic liquidity-filtered stock universe
  setups.py         # pure Setup 1 (breakout) / Setup 2 (pullback) detection functions
  sizing.py         # position sizing math (NetLiq-based, floored)
  exits.py          # initial stop / target / management plan / time-stop (pure)
  guardrails.py     # win-streak throttle, emotional circuit breaker, overtrading guard,
                     # pre-trade checklist gate
  journal.py        # the only module that reads/writes data/trade_journal.jsonl
  reports.py        # weekly metrics report, reading only through journal.py
  cli.py            # CLI entrypoints: scan, size, journal-add, journal-eod-note,
                     # report-weekly, review-positions, circuit-breaker, win-streak,
                     # overtrading-status
tests/
  unit/             # offline, synthetic OHLCV fixtures, no @pytest.mark.integration
  integration/       # real paper Gateway calls, marked @pytest.mark.integration
```

## Design notes

- **Never places an order.** See `korkoban/ibkr_client.py` and
  `tests/unit/test_ibkr_client_boundary.py`.
- **Stops are computed once at entry and never widened or recomputed.** See
  `korkoban/exits.py`.
- **Trade journal** is an append-only JSON Lines file at `data/trade_journal.jsonl`
  (gitignored — local, per-user data, not source).
- **Post-win-streak throttle:** 3 consecutive winning trades (`realized_R > 0`) reduce
  `risk_pct` by 25% for the next 12 trades, then revert. A loss/breakeven resets the streak
  counter. The throttle never increases risk and never stacks.
