"""Every tunable threshold for the KORKOBAN strategy lives here — nowhere else.

Setup-detection, sizing, exit, and guardrail modules import these constants rather than
inlining literals, so a reviewer can see every tunable number in one place (REQ-019).
"""

from __future__ import annotations

from dataclasses import dataclass

# ─── Setup 1 / Setup 2 detection ────────────────────────────────────────────
BREAKOUT_LOOKBACK_DAYS: int = 20
VOLUME_RATIO_MULTIPLE: float = 1.8
AVG_VOLUME_LOOKBACK_DAYS: int = 50
TREND_MA_LOOKBACK_DAYS: int = 100
PULLBACK_MA_LOOKBACK_DAYS: int = 20
ATR_PERIOD: int = 14
ATR_PERCENTILE_WINDOW_DAYS: int = 252
ATR_PERCENTILE_CUTOFF: float = 90.0  # ATR14 must be strictly below this percentile
RETRACEMENT_MIN_PCT: float = 0.38
RETRACEMENT_MAX_PCT: float = 0.50

# ─── Position sizing ─────────────────────────────────────────────────────────
RISK_PCT_DEFAULT: float = 0.005
RISK_PCT_MIN: float = 0.004
RISK_PCT_MAX: float = 0.007

# ─── Exits ───────────────────────────────────────────────────────────────────
STOP_ATR_MULTIPLE_DEFAULT: float = 1.5
STOP_ATR_MULTIPLE_MIN: float = 1.3
STOP_ATR_MULTIPLE_MAX: float = 1.6
TARGET_R_MULTIPLE_DEFAULT: float = 2.5
TARGET_R_MULTIPLE_MIN: float = 2.2
TARGET_R_MULTIPLE_MAX: float = 2.8
SCALE_OUT_R_MULTIPLE: float = 1.8
SCALE_OUT_FRACTION: float = 0.5
TRAIL_ATR_MULTIPLE: float = 1.5
TIME_STOP_BARS_DEFAULT: int = 10
TIME_STOP_BARS_MIN: int = 8
TIME_STOP_BARS_MAX: int = 12

# ─── Guardrails ──────────────────────────────────────────────────────────────
WIN_STREAK_TRIGGER_COUNT: int = 3
WIN_STREAK_RISK_REDUCTION_PCT: float = 0.25
WIN_STREAK_THROTTLE_TRADE_COUNT: int = 12
EMOTIONAL_PAUSE_DAYS: int = 7
OVERTRADING_THRESHOLD_DEFAULT: int = 15
OVERTRADING_THRESHOLD_MIN: int = 12
OVERTRADING_THRESHOLD_MAX: int = 15

# ─── Universe ────────────────────────────────────────────────────────────────
STOCK_SPREAD_MAX_PCT: float = 0.0005  # 0.05%, strict <
STOCK_ADV_MIN_SHARES: float = 5_000_000  # strict >

FUTURES_SYMBOLS: tuple[str, ...] = ("ES", "NQ", "YM", "RTY", "GC", "CL")
MICRO_FUTURES_SYMBOLS: tuple[str, ...] = ("MES", "MNQ", "MYM", "M2K", "MGC", "MCL")

# Point value (USD per 1.00 point move) for every futures contract in the fixed universe,
# including its micro equivalent. This is the single definition site — sizing.py and
# universe.py read from here, never inline (REQ-021).
FUTURES_POINT_VALUES: dict[str, float] = {
    "ES": 50.0,
    "MES": 5.0,
    "NQ": 20.0,
    "MNQ": 2.0,
    "YM": 5.0,
    "MYM": 0.5,
    "RTY": 50.0,
    "M2K": 5.0,
    "GC": 100.0,
    "MGC": 10.0,
    "CL": 1000.0,
    "MCL": 100.0,
}

# ─── IBKR connection defaults (overridden by ibkr.input) ───────────────────
IBKR_DEFAULT_HOST: str = "127.0.0.1"
IBKR_DEFAULT_PORT: int = 4002
IBKR_DEFAULT_CLIENT_ID: int = 17


@dataclass(frozen=True)
class IBKRConnectionConfig:
    host: str
    port: int
    client_id: int


def load_ibkr_config(path: str) -> IBKRConnectionConfig:
    """Parses key=value pairs from `path`; any missing key falls back to the documented default."""
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return IBKRConnectionConfig(
        host=values.get("host", IBKR_DEFAULT_HOST),
        port=int(values.get("port", IBKR_DEFAULT_PORT)),
        client_id=int(values.get("client_id", IBKR_DEFAULT_CLIENT_ID)),
    )
