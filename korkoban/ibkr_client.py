"""The ONLY module in the codebase allowed to import ib_insync's IB object (REQ-001).

Every method here is a read: market data, account summary, or scanner data. No method
submits, modifies, or cancels an order.
"""

from __future__ import annotations

from ib_insync import IB, BarData, ContFuture, Contract, ScanData, ScannerSubscription, Stock

from korkoban import config, setups


class IBKRClient:
    def __init__(self, connection_config: config.IBKRConnectionConfig) -> None:
        self._ib = IB()
        self._connection_config = connection_config

    def connect(self) -> None:
        # readonly=True enforces the Gateway-side Read-Only API guard on top of this wrapper
        self._ib.connect(
            self._connection_config.host,
            self._connection_config.port,
            clientId=self._connection_config.client_id,
            readonly=True,
        )
        # Falls back to delayed market data (3) so stock_bid_ask_spread_pct still works on
        # accounts without a live-data subscription — common on paper accounts. This is a
        # decision-support tool built on daily bars, not latency-sensitive execution, so a
        # delayed bid/ask for the spread-eligibility check is an acceptable trade-off.
        self._ib.reqMarketDataType(3)

    def disconnect(self) -> None:
        self._ib.disconnect()

    def historical_bars(self, contract: Contract, duration: str, bar_size: str) -> list[BarData]:
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        return list(bars)

    def historical_futures_bars(
        self, symbol: str, duration: str = "2 Y", bar_size: str = "1 day"
    ) -> list[setups.Bar]:
        # ContFuture auto-rolls to the current front-month contract; symbol -> exchange is
        # the single lookup site in config.FUTURES_EXCHANGES (REQ-019, no inlined literals).
        contract = ContFuture(symbol, exchange=config.FUTURES_EXCHANGES[symbol], currency="USD")
        raw_bars = self.historical_bars(contract, duration=duration, bar_size=bar_size)
        return [
            setups.Bar(
                date=str(bar.date),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in raw_bars
        ]

    def historical_stock_bars(
        self,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        duration: str = "2 Y",
        bar_size: str = "1 day",
    ) -> list[setups.Bar]:
        contract = Stock(symbol, exchange, currency)
        raw_bars = self.historical_bars(contract, duration=duration, bar_size=bar_size)
        return [
            setups.Bar(
                date=str(bar.date),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in raw_bars
        ]

    def stock_average_daily_volume(
        self,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        lookback_days: int = config.AVG_VOLUME_LOOKBACK_DAYS,
    ) -> float:
        # Reuses config.AVG_VOLUME_LOOKBACK_DAYS (50) as the ADV-eligibility window — the same
        # "50-day average volume" convention already established for Setup 1's volume-ratio
        # trigger; INSTRUCTIONS.md doesn't specify a separate window for universe eligibility.
        bars = self.historical_stock_bars(
            symbol, exchange=exchange, currency=currency, duration=f"{lookback_days + 10} D"
        )
        recent = bars[-lookback_days:]
        if not recent:
            raise ValueError(f"no historical volume data available for {symbol}")
        return sum(bar.volume for bar in recent) / len(recent)

    def stock_bid_ask_spread_pct(
        self, symbol: str, exchange: str = "SMART", currency: str = "USD"
    ) -> float:
        # reqTickers is ib_insync's blocking, synchronous snapshot helper — it waits for the
        # ticker to populate before returning, unlike the async reqMktData + event-callback path.
        contract = Stock(symbol, exchange, currency)
        ticker = self._ib.reqTickers(contract)[0]
        bid, ask = ticker.bid, ticker.ask
        if not (bid > 0 and ask > 0):  # NaN comparisons are always False, so this also
            # catches ib_insync's "no live quote" sentinel (NaN bid/ask)
            raise ValueError(f"no live bid/ask quote available for {symbol}")
        mid = (bid + ask) / 2
        return (ask - bid) / mid

    def stock_candidate_symbols(
        self,
        instrument: str = "STK",
        location_code: str = "STK.US.MAJOR",
        scan_code: str = "TOP_PERC_GAIN",
        above_volume: int = 0,
        number_of_rows: int = 50,
    ) -> list[str]:
        rows = self.stock_candidate_scan(
            instrument=instrument,
            location_code=location_code,
            scan_code=scan_code,
            above_volume=above_volume,
            number_of_rows=number_of_rows,
        )
        return [
            row.contractDetails.contract.symbol
            for row in rows
            if row.contractDetails.contract is not None
        ]

    def account_net_liquidation(self) -> float:
        for value in self._ib.accountSummary():
            if value.tag == "NetLiquidation":
                return float(value.value)
        raise ValueError("NetLiquidation tag not found in account summary")

    def stock_candidate_scan(
        self,
        instrument: str = "STK",
        location_code: str = "STK.US.MAJOR",
        scan_code: str = "TOP_PERC_GAIN",
        above_volume: int = 0,
        number_of_rows: int = 50,
    ) -> list[ScanData]:
        # scanner subscription, not an order subscription — read-only liquidity/candidate feed
        subscription = ScannerSubscription(
            numberOfRows=number_of_rows,
            instrument=instrument,
            locationCode=location_code,
            scanCode=scan_code,
            aboveVolume=above_volume,
        )
        return list(self._ib.reqScannerData(subscription))


def load_client(path: str = "ibkr.input") -> IBKRClient:
    client = IBKRClient(config.load_ibkr_config(path))
    client.connect()
    return client
