"""The ONLY module in the codebase allowed to import ib_insync's IB object (REQ-001).

Every method here is a read: market data, account summary, or scanner data. No method
submits, modifies, or cancels an order.
"""
from __future__ import annotations

from ib_insync import IB, Contract, ScannerSubscription

from korkoban import config


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

    def disconnect(self) -> None:
        self._ib.disconnect()

    def historical_bars(self, contract: Contract, duration: str, bar_size: str) -> list[object]:
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
        )
        return list(bars)

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
    ) -> list[object]:
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
    return IBKRClient(config.load_ibkr_config(path))
