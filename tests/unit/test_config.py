# REQ-016, REQ-021
"""Tests for korkoban.config: ibkr.input parsing/defaults, futures point-value mapping,
and the .gitignore / hardcoded-connect-literal structural audits required by REQ-016.
"""

from __future__ import annotations

from pathlib import Path

from korkoban import config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_load_ibkr_config_parses_sample_file(tmp_path: Path) -> None:
    # TC-016-01: parses host/port/client_id from sample ibkr.input
    sample = tmp_path / "ibkr.input"
    sample.write_text("host=10.0.0.5\nport=7497\nclient_id=42\n", encoding="utf-8")

    result = config.load_ibkr_config(str(sample))

    assert result.host == "10.0.0.5"
    assert result.port == 7497
    assert result.client_id == 42


def test_load_ibkr_config_missing_keys_fall_back_to_defaults(tmp_path: Path) -> None:
    # TC-016-02: missing keys fall back to documented defaults
    sample = tmp_path / "ibkr.input"
    sample.write_text("port=7497\n", encoding="utf-8")

    result = config.load_ibkr_config(str(sample))

    assert result.host == config.IBKR_DEFAULT_HOST
    assert result.port == 7497
    assert result.client_id == config.IBKR_DEFAULT_CLIENT_ID


def test_load_ibkr_config_missing_file_falls_back_to_all_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.input"

    result = config.load_ibkr_config(str(missing))

    assert result.host == config.IBKR_DEFAULT_HOST
    assert result.port == config.IBKR_DEFAULT_PORT
    assert result.client_id == config.IBKR_DEFAULT_CLIENT_ID


def test_ibkr_client_has_no_hardcoded_connect_literal() -> None:
    # TC-016-03: grep audit finds no hardcoded connect() literal
    source = (REPO_ROOT / "korkoban" / "ibkr_client.py").read_text(encoding="utf-8")
    assert "connect(" in source
    assert "127.0.0.1" not in source
    assert "4002" not in source


def test_gitignore_excludes_ibkr_input() -> None:
    # TC-016-04: .gitignore contains ibkr.input
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "ibkr.input" in gitignore.splitlines()


def test_volume_ratio_multiple_for_uses_override_when_present() -> None:
    assert config.volume_ratio_multiple_for("NQ") == config.VOLUME_RATIO_MULTIPLE_OVERRIDES["NQ"]
    assert config.volume_ratio_multiple_for("YM") == config.VOLUME_RATIO_MULTIPLE_OVERRIDES["YM"]


def test_volume_ratio_multiple_for_falls_back_to_global_default() -> None:
    assert config.volume_ratio_multiple_for("ES") == config.VOLUME_RATIO_MULTIPLE


def test_futures_point_values_cover_full_universe_incl_micros() -> None:
    # TC-021-01: config.py exposes full point-value mapping incl. micros
    for symbol in config.FUTURES_SYMBOLS:
        assert symbol in config.FUTURES_POINT_VALUES
    for symbol in config.MICRO_FUTURES_SYMBOLS:
        assert symbol in config.FUTURES_POINT_VALUES
    assert config.FUTURES_POINT_VALUES["ES"] == 50.0
    assert config.FUTURES_POINT_VALUES["MES"] == 5.0
