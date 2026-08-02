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
