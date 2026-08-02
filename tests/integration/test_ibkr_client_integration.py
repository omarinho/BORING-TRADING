# REQ-001, REQ-005
"""Integration-tier smoke tests against a real paper IB Gateway; skip gracefully via the
ibkr_gateway fixture (tests/integration/conftest.py) when no Gateway is reachable here.
"""

from __future__ import annotations

import pytest

from .conftest import GatewayConnection


@pytest.mark.integration
def test_tc_001_03_connect_uses_readonly_true_against_real_gateway(
    ibkr_gateway: GatewayConnection,
) -> None:
    assert ibkr_gateway.connect_kwargs.get("readonly") is True


@pytest.mark.integration
def test_account_net_liquidation_read_only_smoke(ibkr_gateway: GatewayConnection) -> None:
    # REQ-005: read-only account-summary pull, no order-submission path involved
    net_liq = ibkr_gateway.client.account_net_liquidation()
    assert isinstance(net_liq, float)


@pytest.mark.integration
def test_historical_futures_bars_real_smoke(ibkr_gateway: GatewayConnection) -> None:
    # REQ-002/003 scan wiring: real ContFuture construction + reqHistoricalData round-trip
    bars = ibkr_gateway.client.historical_futures_bars("ES", duration="30 D")
    assert isinstance(bars, list)
    assert len(bars) > 0
    assert all(bar.close > 0 and bar.volume >= 0 for bar in bars)


@pytest.mark.integration
def test_historical_stock_bars_real_smoke(ibkr_gateway: GatewayConnection) -> None:
    # REQ-005 scan wiring: real Stock contract construction + reqHistoricalData round-trip
    bars = ibkr_gateway.client.historical_stock_bars("AAPL", duration="30 D")
    assert isinstance(bars, list)
    assert len(bars) > 0
    assert all(bar.close > 0 and bar.volume >= 0 for bar in bars)


@pytest.mark.integration
def test_stock_average_daily_volume_real_smoke(ibkr_gateway: GatewayConnection) -> None:
    adv = ibkr_gateway.client.stock_average_daily_volume("AAPL", lookback_days=10)
    assert isinstance(adv, float)
    assert adv > 0


@pytest.mark.integration
def test_stock_candidate_symbols_real_smoke(ibkr_gateway: GatewayConnection) -> None:
    symbols = ibkr_gateway.client.stock_candidate_symbols()
    assert isinstance(symbols, list)
    assert all(isinstance(symbol, str) for symbol in symbols)


@pytest.mark.integration
def test_stock_bid_ask_spread_pct_real_smoke(ibkr_gateway: GatewayConnection) -> None:
    # A live bid/ask isn't guaranteed outside market hours — accept either a valid spread
    # or the documented ValueError for "no live quote available" (both are correct
    # behavior, not a test failure either way).
    try:
        spread_pct = ibkr_gateway.client.stock_bid_ask_spread_pct("AAPL")
        assert spread_pct >= 0
    except ValueError as exc:
        assert "no live bid/ask quote available" in str(exc)
