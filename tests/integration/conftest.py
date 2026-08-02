"""Integration-tier fixtures: skip gracefully when no paper IB Gateway is reachable.

A missing Gateway in this dev environment is an expected, not exceptional, condition —
this is the one deliberate exception to "no silent except" in this codebase.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import NamedTuple
from unittest.mock import patch

import pytest
from ib_insync import IB

from korkoban.ibkr_client import IBKRClient, load_client


class GatewayConnection(NamedTuple):
    client: IBKRClient
    connect_kwargs: dict[str, object]


@pytest.fixture
def ibkr_gateway() -> Iterator[GatewayConnection]:
    client = load_client()
    captured_kwargs: dict[str, object] = {}
    original_connect = IB.connect

    def _spy_connect(
        self: IB,
        host: str = "127.0.0.1",
        port: int = 7497,
        clientId: int = 1,
        timeout: float = 4,
        readonly: bool = False,
        account: str = "",
    ) -> None:
        captured_kwargs.update(
            {
                "host": host,
                "port": port,
                "clientId": clientId,
                "timeout": timeout,
                "readonly": readonly,
                "account": account,
            }
        )
        original_connect(self, host, port, clientId, timeout, readonly, account)

    try:
        with patch.object(IB, "connect", _spy_connect):
            client.connect()
    except Exception as exc:  # deliberate: missing Gateway is expected here, not a real failure
        pytest.skip(f"no paper IB Gateway reachable: {exc}")

    yield GatewayConnection(client=client, connect_kwargs=captured_kwargs)
    client.disconnect()
