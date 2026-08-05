# REQ-002 (scan wiring)
"""Unit tests for IBKRClient.historical_futures_bars: contract construction (ContFuture with
the configured exchange) and raw-bar-to-setups.Bar conversion. historical_bars() itself is
mocked so this stays a pure conversion/wiring test with zero real network/Gateway dependency.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from korkoban import config
from korkoban.ibkr_client import IBKRClient, load_client
from korkoban.setups import Bar

_CONNECTION_CONFIG = config.IBKRConnectionConfig(host="127.0.0.1", port=4002, client_id=1)


def test_load_client_connects_before_returning(tmp_path: Path) -> None:
    # A previously-real bug: load_client() constructed an IBKRClient but never called
    # .connect() on it, so every production code path (scan/size/review-positions) would
    # fail with "Not connected" the first time it touched a client-method that needs the
    # Gateway — invisible to every unit test because they all inject a fake client_factory
    # that bypasses load_client() entirely. Only a real CLI invocation caught this.
    ibkr_input_path = str(tmp_path / "ibkr.input")  # nonexistent file -> falls back to defaults
    with patch.object(IBKRClient, "connect") as mock_connect:
        load_client(ibkr_input_path)
    mock_connect.assert_called_once()


def _fake_raw_bar(
    day: str, open_: float, high: float, low: float, close: float, volume: float
) -> SimpleNamespace:
    return SimpleNamespace(date=day, open=open_, high=high, low=low, close=close, volume=volume)


def test_historical_futures_bars_builds_contfuture_with_configured_exchange() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    with patch.object(client, "historical_bars", return_value=[]) as mock_historical_bars:
        client.historical_futures_bars("ES")

    contract = mock_historical_bars.call_args.args[0]
    assert contract.symbol == "ES"
    assert contract.exchange == config.FUTURES_EXCHANGES["ES"]


def test_historical_futures_bars_converts_raw_bars_to_setups_bar() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    raw_bars = [_fake_raw_bar("2026-01-01", 100.0, 101.0, 99.0, 100.5, 1000.0)]
    with patch.object(client, "historical_bars", return_value=raw_bars):
        bars = client.historical_futures_bars("NQ")

    assert bars == [
        Bar(date="2026-01-01", open=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0)
    ]


def test_historical_futures_bars_passes_duration_and_bar_size_through() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    with patch.object(client, "historical_bars", return_value=[]) as mock_historical_bars:
        client.historical_futures_bars("ES", duration="1 Y", bar_size="1 day")

    _, kwargs = mock_historical_bars.call_args
    assert kwargs["duration"] == "1 Y"
    assert kwargs["bar_size"] == "1 day"


def test_historical_futures_bars_raises_key_error_for_unknown_symbol() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    with patch.object(client, "historical_bars", return_value=[]):
        try:
            client.historical_futures_bars("ZZZ")
        except KeyError:
            return
    raise AssertionError("expected KeyError for a symbol outside config.FUTURES_EXCHANGES")


# ─── Stock-universe live scanning (REQ-005 end-to-end) ──────────────────────────────────────


def test_historical_stock_bars_builds_stock_contract_and_converts_bars() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    raw_bars = [_fake_raw_bar("2026-01-01", 10.0, 11.0, 9.0, 10.5, 2_000_000.0)]
    with patch.object(client, "historical_bars", return_value=raw_bars) as mock_historical_bars:
        bars = client.historical_stock_bars("AAPL")

    contract = mock_historical_bars.call_args.args[0]
    assert contract.symbol == "AAPL"
    assert contract.exchange == "SMART"
    assert bars == [
        Bar(date="2026-01-01", open=10.0, high=11.0, low=9.0, close=10.5, volume=2_000_000.0)
    ]


def test_stock_average_daily_volume_averages_the_lookback_window() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    raw_bars = [
        _fake_raw_bar(f"2026-01-{i:02d}", 10.0, 11.0, 9.0, 10.5, float(1_000_000 * i))
        for i in range(1, 11)
    ]
    with patch.object(client, "historical_bars", return_value=raw_bars):
        adv = client.stock_average_daily_volume("AAPL", lookback_days=10)

    assert adv == sum(1_000_000 * i for i in range(1, 11)) / 10


def test_stock_average_daily_volume_raises_when_no_history() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    with patch.object(client, "historical_bars", return_value=[]):
        try:
            client.stock_average_daily_volume("AAPL", lookback_days=10)
        except ValueError:
            return
    raise AssertionError("expected ValueError when no historical volume data is available")


def _fake_tick(bid: float, ask: float) -> SimpleNamespace:
    return SimpleNamespace(priceBid=bid, priceAsk=ask)


def test_stock_bid_ask_spread_pct_computed_from_last_historical_tick() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    # IBKR can return more ticks than numberOfTicks requests; the last one (chronologically
    # closest to endDateTime, i.e. closest to the regular session's close) is the one that
    # matters, not the first.
    ticks = [_fake_tick(90.0, 92.0), _fake_tick(99.0, 101.0)]
    with patch.object(client, "_ib", SimpleNamespace(reqHistoricalTicks=lambda *_a, **_kw: ticks)):
        spread_pct = client.stock_bid_ask_spread_pct("AAPL")

    assert spread_pct == (101.0 - 99.0) / 100.0


def test_stock_bid_ask_spread_pct_passes_bid_ask_and_regular_hours_only() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    ticks = [_fake_tick(99.0, 101.0)]
    with patch.object(
        client, "_ib", SimpleNamespace(reqHistoricalTicks=Mock(return_value=ticks))
    ) as fake_ib:
        client.stock_bid_ask_spread_pct("AAPL")

    _, kwargs = fake_ib.reqHistoricalTicks.call_args
    assert kwargs["whatToShow"] == "BID_ASK"
    assert kwargs["useRth"] is True


def test_stock_bid_ask_spread_pct_raises_when_no_ticks_available() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    with patch.object(client, "_ib", SimpleNamespace(reqHistoricalTicks=lambda *_a, **_kw: [])):
        try:
            client.stock_bid_ask_spread_pct("AAPL")
        except ValueError:
            return
    raise AssertionError("expected ValueError when no historical bid/ask ticks are available")


def test_stock_bid_ask_spread_pct_raises_when_last_tick_has_no_valid_quote() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    ticks = [_fake_tick(float("nan"), float("nan"))]
    with patch.object(client, "_ib", SimpleNamespace(reqHistoricalTicks=lambda *_a, **_kw: ticks)):
        try:
            client.stock_bid_ask_spread_pct("AAPL")
        except ValueError:
            return
    raise AssertionError("expected ValueError when the last tick has no valid bid/ask")


def test_stock_candidate_symbols_extracts_symbols_from_scanner_rows() -> None:
    client = IBKRClient(_CONNECTION_CONFIG)
    row_a = SimpleNamespace(
        contractDetails=SimpleNamespace(contract=SimpleNamespace(symbol="AAPL"))
    )
    row_b = SimpleNamespace(
        contractDetails=SimpleNamespace(contract=SimpleNamespace(symbol="MSFT"))
    )
    with patch.object(client, "stock_candidate_scan", return_value=[row_a, row_b]):
        symbols = client.stock_candidate_symbols()

    assert symbols == ["AAPL", "MSFT"]
