"""Weekend maintenance script: refresh data/stock_universe.json from its two upstream
constituent lists (S&P 500 + Nasdaq 100), report what changed, and overwrite the file in
place. Intended to run manually (or via a scheduled task) after Friday's weekly review --
the result is an ordinary working-tree change, reviewed and committed by hand like any
other edit, not an auto-commit.

Lives outside korkoban/ (not part of the fixed module set pinned by
tests/unit/test_package_layout.py) because it does network I/O against GitHub, unrelated to
the read-only IBKR boundary the rest of the package enforces.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STOCK_UNIVERSE_PATH = REPO_ROOT / "data" / "stock_universe.json"

SP500_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/"
    "constituents.csv"
)
NASDAQ100_URL = "https://yfiua.github.io/index-constituents/constituents-nasdaq100.csv"

# Sanity floors, not exact counts (real membership drifts a little between rebalances) --
# catch a truncated or restructured source before it silently corrupts the production
# universe file, without hardcoding today's exact 503/101 split.
SP500_MIN_COUNT = 450
NASDAQ100_MIN_COUNT = 90

SOURCE_DESCRIPTION = (
    "Union of S&P 500 (github.com/datasets/s-and-p-500-companies) and Nasdaq-100 "
    "(github.com/yfiua/index-constituents) constituents. Dotted share-class tickers "
    "(e.g. BRK.B, BF.B) rewritten with a space for IBKR's local-symbol convention "
    "(BRK B, BF B). Refreshed by scripts/refresh_stock_universe.py; safe to run weekly, "
    "review the git diff before committing."
)


def _fetch_symbols(url: str, min_count: int, label: str) -> list[str]:
    with urllib.request.urlopen(url, timeout=30) as response:
        text = response.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    symbols = [row["Symbol"].strip() for row in rows if row["Symbol"].strip()]
    if len(symbols) < min_count:
        raise ValueError(
            f"{label} fetch returned only {len(symbols)} tickers, expected at least "
            f"{min_count} -- source likely broken or restructured. Aborting without "
            "touching the universe file."
        )
    return symbols


def fetch_universe() -> list[str]:
    sp500 = _fetch_symbols(SP500_URL, SP500_MIN_COUNT, "S&P 500")
    nasdaq100 = _fetch_symbols(NASDAQ100_URL, NASDAQ100_MIN_COUNT, "Nasdaq 100")
    union = {ticker.replace(".", " ") for ticker in sp500 + nasdaq100}
    return sorted(union)


def main() -> None:
    new_symbols = fetch_universe()

    old_data = json.loads(STOCK_UNIVERSE_PATH.read_text(encoding="utf-8"))
    old_symbols = set(old_data["symbols"])
    new_symbol_set = set(new_symbols)

    added = sorted(new_symbol_set - old_symbols)
    removed = sorted(old_symbols - new_symbol_set)

    STOCK_UNIVERSE_PATH.write_text(
        json.dumps(
            {
                "last_updated": date.today().isoformat(),
                "source": SOURCE_DESCRIPTION,
                "symbols": new_symbols,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"{STOCK_UNIVERSE_PATH} refreshed: {len(new_symbols)} symbols (was {len(old_symbols)})")
    if added:
        print(f"Added ({len(added)}): {added}")
    if removed:
        print(f"Removed ({len(removed)}): {removed}")
    if not added and not removed:
        print("No changes.")


if __name__ == "__main__":
    main()
