# KORKOBAN Daily Routine

Step-by-step operational guide for running the system manually, Monday through Friday, on
this machine. This document is a "what do I do today" checklist — to understand what each
command does internally, see `README.md`.

**Golden rule, no exceptions: KORKOBAN never submits orders.** Every alert it produces is
information for you to evaluate and act on manually in TWS. The system never touches the
buy/sell button.

---

## When to run it

**Monday through Friday, after 6:00 PM Bogotá time.** By then, both the stock market (closes
3-4 PM Bogotá depending on US daylight saving) and the futures in scope (ES, NQ, YM, RTY, GC,
CL) have closed, so the daily bar is already settled in IBKR. Running it earlier gives you a
"today" bar that's still incomplete, and the signals won't mean anything evaluated that way.

No need to run it more than once a day, or on weekends (no new bar forms).

---

## Before you start (once, at the beginning of the session)

1. Open **IB Gateway** (or TWS) and log in to the paper account.
2. Confirm the connection status shows **"API Client: connected"** (not red/"disconnected").
3. Confirm **Read-Only API** is still enabled: `Configure → Settings → API` → checkbox
   checked. This is an infrastructure-level guarantee that the system can never submit an
   order, even if the code had a bug.
4. Open a terminal in `G:\repositories\BORING-TRADING`.

---

## Step 1 — Scan the universe

```bash
.venv/Scripts/python.exe -m korkoban.cli scan
```

You'll see one of two outputs:

**No signals (the most common case — the system is designed to be "boring"):**
```
No signals — 0 candidates matched Setup 1 or Setup 2 this scan.
```
Nothing to do. Move on to Step 2.

**One or more alerts:**
```
ALERT: ES setup=1 direction=long entry=5123.25 atr14=42.1 stop=5060.1 target=5281.5
```
Each line gives you: symbol, setup (1=breakout, 2=pullback), direction, suggested entry
price, ATR14, and stop/target already computed. This **is not an executed order** — it's
the signal for you to evaluate and, if you decide to take it, execute manually in TWS.

You can ignore terminal messages like `Error 162 ... API scanner subscription cancelled` —
that's normal IBKR noise when the scanner closes after returning results, not a real error.

---

## Step 2 — If you're taking an alert

1. **Before anything else, answer honestly:** *"Am I taking this because it matches the
   measurable edge, or because I need action / need to be right / need to recover?"* That
   answer is required in the log entry (Step 4).
2. Compute the position size:
   ```bash
   .venv/Scripts/python.exe -m korkoban.cli size --stop-distance <stop_points> --symbol <SYMBOL>
   ```
   NetLiq is read live from the account (no need to type it in). If the win-streak throttle
   is active, the command will tell you and automatically use the reduced risk_pct.
3. **Execute the order yourself in TWS as a bracket order** — see the two worked examples
   below.
4. Take a screenshot of the entry (for the `--screenshot-path` field in the log entry).

**One important caveat:** `entry`/`atr14` in the alert are computed from the prior session's
already-closed bar. If the price you actually get filled at differs from the alert's `entry`
by more than a few ticks, treat `stop`/`target` as reference distances (points away from
entry), not literal prices to type in verbatim — a stop that's `entry - 1.5×atr14` should
stay `your_fill - 1.5×atr14`, not the alert's original number, if your fill moved.

### Worked example — LONG

You see:
```
ALERT: MES setup=1 direction=long entry=5123.25 atr14=42.1 stop=5060.1 target=5281.12
```

1. Compute size (assume the command reports `units=2` for this NetLiq/account):
   ```bash
   .venv/Scripts/python.exe -m korkoban.cli size --stop-distance 63.15 --symbol MES
   # -> units=2 risk_dollars=750.0 dollars_per_unit=315.75
   ```
   (`63.15` = `entry - stop` = `5123.25 - 5060.1`, i.e. the stop distance in points.)
2. In TWS: right-click **MES** → **Trade** → **Bracket Order**.
3. Fill in:
   - **Action:** BUY, **Quantity:** `2` (from the `size` output).
   - **Entry:** market, or a limit near the current price if you don't want to chase it.
   - **Attached stop (SELL STOP):** `5060.1`.
   - **Attached target (SELL LIMIT):** `5281.12`.
4. Review the ticket, confirm quantity/prices, **Transmit**.
5. The stop and target are now live as an OCO pair in TWS — whichever fills first
   automatically cancels the other. KORKOBAN never touches this; from here it's entirely
   TWS's native bracket-order mechanism.

### Worked example — SHORT

You see:
```
ALERT: MNQ setup=1 direction=short entry=18500.0 atr14=180.0 stop=18770.0 target=17825.0
```

1. Compute size (assume `units=1` for this NetLiq/account):
   ```bash
   .venv/Scripts/python.exe -m korkoban.cli size --stop-distance 270 --symbol MNQ
   # -> units=1 risk_dollars=750.0 dollars_per_unit=540.0
   ```
   (`270` = `stop - entry` = `18770.0 - 18500.0`; for a short, the stop sits *above* entry.)
2. In TWS: right-click **MNQ** → **Trade** → **Bracket Order**.
3. Fill in:
   - **Action:** SELL, **Quantity:** `1`.
   - **Entry:** market, or a limit near the current price.
   - **Attached stop (BUY STOP):** `18770.0` — above entry, since a short loses money if
     price rises.
   - **Attached target (BUY LIMIT):** `17825.0` — below entry, since a short profits if
     price falls.
4. Review, **Transmit**.

The only real difference between long and short: for a long the stop is *below* entry and
the target *above*; for a short it's flipped. `exits.compute_initial_stop`/`compute_target`
already handle this — the `stop`/`target` values printed in the alert are always correct for
that alert's direction, you don't need to flip anything yourself.

---

## Step 3 — Review open positions

```bash
.venv/Scripts/python.exe -m korkoban.cli review-positions
```

Marks with `FLAG:` any position that's gone 10 bars without reaching 1R — a signal for you
to manually review whether it's worth closing. `OK:` means it's still within the normal
window. This also doesn't close anything on its own — it's a flag for manual review.

---

## Step 4 — Log any trade you executed today

```bash
.venv/Scripts/python.exe -m korkoban.cli journal-add \
  --symbol ES --direction long --setup 1 \
  --entry-price 5123.25 --stop-price 5060.1 --target-price 5281.5 \
  --size 2 --risk-dollars 500 \
  --checklist-gate-answer edge_based \
  --reasoning "matches the 20d breakout, volume 2.1x, 100d trend aligned" \
  --screenshot-path "screenshots/es_2026-08-02.png"
```

Notes on the fields:
- `--checklist-gate-answer` only accepts `edge_based` or `impulse`. If it's `impulse` (you
  entered out of a need for action, not because of the edge), the trade is still logged but
  **doesn't count** toward win-rate/expectancy statistics — this keeps the tracked edge honest.
- `--reasoning` and `--screenshot-path` are required, no exceptions.
- If you closed a prior trade today, add `--realized-r <number>` (in R units, not dollars)
  when logging it — that's what updates the winning-streak counter.
- If you want the optional management plan (scale 50% at 1.8R, trail remainder at 1.5×ATR),
  add `--with-management-plan`.

If the emotional circuit breaker is active, this command will reject the log entry with a
clear message — that's the guardrail working, not an error.

---

## Step 5 — End-of-day note

```bash
.venv/Scripts/python.exe -m korkoban.cli journal-eod-note "how I felt trading today"
```

One note per day, free text. If you already logged one today, the command will tell you and
reject the second one.

---

## Guardrail checks (whenever you want, not necessarily daily)

```bash
.venv/Scripts/python.exe -m korkoban.cli win-streak status        # throttle active? reduced risk_pct?
.venv/Scripts/python.exe -m korkoban.cli overtrading-status       # how many trades this month
.venv/Scripts/python.exe -m korkoban.cli circuit-breaker status   # emotional pause active?
```

### Emotional circuit breaker (only use it if you genuinely need to)

If you feel you're about to trade out of a need to prove something or to recover from a bad
stretch, flip it yourself:

```bash
.venv/Scripts/python.exe -m korkoban.cli circuit-breaker flip
```

**This is real and cannot be shortened.** Once activated, it blocks new `scan` alerts and new
`journal-add` entries for **exactly 7 calendar days**, and running `flip` again does not
shorten the pause — that's the guardrail working as designed.

---

## Weekly review

**Run this on Fridays** (or the last business day of the week, on a short week), as part of
the same after-6PM session as Step 1-5 — not a separate daily habit.

```bash
.venv/Scripts/python.exe -m korkoban.cli report-weekly --start YYYY-MM-DD --end YYYY-MM-DD
```

`--start`/`--end` are inclusive. On a Friday, use that week's Monday as `--start` and
today's date as `--end` — e.g. running it Friday 2026-08-07, the range is:

```bash
.venv/Scripts/python.exe -m korkoban.cli report-weekly --start 2026-08-03 --end 2026-08-07
```

Gives you: expectancy in R (over the last 50 counted trades — not clipped to just this
week), max drawdown, count of trades forced by overtrading, and zero-signal days in the
range — a high number here is good, it means the system is being selective.

---

## Common issues

- **"Could not connect to IBKR Gateway"** → Gateway/TWS isn't running or isn't logged in.
  Open it and retry.
- **`Error 10089` messages about data subscriptions** → your account has no live data for
  that particular stock; the system automatically falls back to delayed data — this is
  normal and doesn't block scanning.
- **"Socket disconnect" on back-to-back runs** → avoid running `scan` many times in quick
  succession; one run a day is enough and avoids saturating the IBKR connection.
