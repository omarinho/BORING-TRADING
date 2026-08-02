# REQ-005
"""Unit tests for korkoban.universe: futures point-value coverage and stock eligibility."""

from __future__ import annotations

from korkoban import config
from korkoban.universe import (
    FUTURES_UNIVERSE,
    StockCandidate,
    filter_stock_universe,
    futures_point_value,
    is_eligible_stock,
)


def test_futures_universe_covers_all_symbols_and_micros_with_correct_point_values() -> None:
    # TC-005-01
    assert set(FUTURES_UNIVERSE) == set(config.FUTURES_SYMBOLS)
    all_symbols = set(config.FUTURES_SYMBOLS) | set(config.MICRO_FUTURES_SYMBOLS)
    assert set(config.FUTURES_POINT_VALUES.keys()) == all_symbols
    for symbol, expected_value in config.FUTURES_POINT_VALUES.items():
        assert futures_point_value(symbol) == expected_value


def test_eligible_stock_within_spread_and_volume_thresholds() -> None:
    # TC-005-02
    candidate = StockCandidate(
        symbol="AAA", spread_pct=0.0004, avg_daily_volume=6_000_000.0, asset_class="stock"
    )
    assert is_eligible_stock(candidate) is True
    assert filter_stock_universe([candidate]) == [candidate]


def test_stock_excluded_when_spread_too_wide() -> None:
    # TC-005-03
    candidate = StockCandidate(
        symbol="BBB", spread_pct=0.0006, avg_daily_volume=6_000_000.0, asset_class="stock"
    )
    assert is_eligible_stock(candidate) is False
    assert filter_stock_universe([candidate]) == []


def test_stock_excluded_when_adv_too_low() -> None:
    # TC-005-04
    candidate = StockCandidate(
        symbol="CCC", spread_pct=0.0004, avg_daily_volume=4_000_000.0, asset_class="stock"
    )
    assert is_eligible_stock(candidate) is False


def test_stock_excluded_when_spread_exactly_at_max_boundary() -> None:
    # TC-005-05 — strict <, so exactly at the max is excluded
    candidate = StockCandidate(
        symbol="DDD",
        spread_pct=config.STOCK_SPREAD_MAX_PCT,
        avg_daily_volume=6_000_000.0,
        asset_class="stock",
    )
    assert is_eligible_stock(candidate) is False


def test_stock_excluded_when_adv_exactly_at_min_boundary() -> None:
    # TC-005-06 — strict >, so exactly at the min is excluded
    candidate = StockCandidate(
        symbol="EEE",
        spread_pct=0.0004,
        avg_daily_volume=config.STOCK_ADV_MIN_SHARES,
        asset_class="stock",
    )
    assert is_eligible_stock(candidate) is False


def test_non_stock_asset_classes_excluded_regardless_of_metrics() -> None:
    # TC-005-07 — forex/small_cap/option excluded even with ideal spread/ADV numbers
    for asset_class in ("forex", "small_cap", "option"):
        candidate = StockCandidate(
            symbol="FFF", spread_pct=0.0001, avg_daily_volume=10_000_000.0, asset_class=asset_class
        )
        assert is_eligible_stock(candidate) is False
