"""Fixed futures universe (point values) and the stock-eligibility filter (REQ-005)."""

from __future__ import annotations

from dataclasses import dataclass

from korkoban import config


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    spread_pct: float
    avg_daily_volume: float
    asset_class: str


FUTURES_UNIVERSE: tuple[str, ...] = config.FUTURES_SYMBOLS


def futures_point_value(symbol: str) -> float:
    return config.FUTURES_POINT_VALUES[symbol]


def is_eligible_stock(candidate: StockCandidate) -> bool:
    if candidate.asset_class != "stock":
        return False
    return (
        candidate.spread_pct < config.STOCK_SPREAD_MAX_PCT
        and candidate.avg_daily_volume > config.STOCK_ADV_MIN_SHARES
    )


def filter_stock_universe(candidates: list[StockCandidate]) -> list[StockCandidate]:
    return [candidate for candidate in candidates if is_eligible_stock(candidate)]
