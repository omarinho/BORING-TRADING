# REQ-001
"""Tests that the IBKR read-only boundary holds: no order-submission call anywhere in
korkoban/, only ibkr_client.py imports ib_insync's IB object, connect() is read-only, and
the README documents the Gateway-side Read-Only API requirement.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from korkoban import config
from korkoban.ibkr_client import IBKRClient

REPO_ROOT = Path(__file__).resolve().parents[2]
KORKOBAN_DIR = REPO_ROOT / "korkoban"

ORDER_SUBMISSION_SUBSTRINGS = ("placeOrder", "cancelOrder", "modifyOrder")


def _korkoban_py_files() -> list[Path]:
    return sorted(KORKOBAN_DIR.glob("*.py"))


def test_tc_001_01_no_order_submission_call_anywhere_in_korkoban() -> None:
    for py_file in _korkoban_py_files():
        source = py_file.read_text(encoding="utf-8")
        for banned in ORDER_SUBMISSION_SUBSTRINGS:
            assert banned not in source, f"{banned} found in {py_file.name}"


def test_tc_001_02_only_ibkr_client_imports_ib_insync() -> None:
    matches = []
    for py_file in _korkoban_py_files():
        source = py_file.read_text(encoding="utf-8")
        if "from ib_insync import" in source or "import ib_insync" in source:
            matches.append(py_file.name)
    assert matches == ["ibkr_client.py"]


def test_tc_001_04_readme_documents_read_only_api_gateway_setting() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "read-only api" in readme.lower()


def test_connect_uses_readonly_true() -> None:
    connection_config = config.IBKRConnectionConfig(host="10.0.0.1", port=7497, client_id=99)
    client = IBKRClient(connection_config)
    with patch.object(client, "_ib", MagicMock()) as mock_ib:
        client.connect()
    _, kwargs = mock_ib.connect.call_args
    assert kwargs["readonly"] is True
    assert mock_ib.connect.call_args.args == ("10.0.0.1", 7497)
    assert kwargs["clientId"] == 99
