# REQ-019
"""Structural audit of the korkoban/ package layout: the fixed module set, config-only
tunables, and that setups.py stays a pure function module with no I/O.

Some of these modules are owned by other agents and may not exist yet when this file is
first run — a clear file-not-found failure for those is expected CORRECT_RED, not a bug
here (see task notes for TC-019-01 / TC-019-03).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KORKOBAN_DIR = REPO_ROOT / "korkoban"

EXPECTED_MODULES = {
    "config.py",
    "ibkr_client.py",
    "universe.py",
    "setups.py",
    "sizing.py",
    "exits.py",
    "guardrails.py",
    "journal.py",
    "reports.py",
    "cli.py",
}

CONFIG_CONSUMER_MODULES = ("sizing.py", "exits.py", "guardrails.py", "setups.py")


def test_tc_019_01_package_contains_exactly_the_fixed_module_set() -> None:
    actual = {f.name for f in KORKOBAN_DIR.glob("*.py") if f.name != "__init__.py"}
    assert actual == EXPECTED_MODULES


def test_tc_019_02_config_consumers_import_config_module() -> None:
    for name in CONFIG_CONSUMER_MODULES:
        path = KORKOBAN_DIR / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        if "config." not in source:
            continue
        assert (
            "from korkoban import config" in source or "import korkoban.config" in source
        ), f"{name} references config. but does not import the config module"


def test_tc_019_03_setups_is_pure_no_ib_insync_no_file_io() -> None:
    path = KORKOBAN_DIR / "setups.py"
    assert path.exists(), "setups.py not found yet (expected CORRECT_RED, owned by another agent)"
    source = path.read_text(encoding="utf-8")
    # Check for actual import statements, not just any mention of "ib_insync" (e.g. a
    # docstring documenting the absence, as in setups.py's own module docstring).
    assert "from ib_insync import" not in source
    assert "import ib_insync" not in source
    assert "open(" not in source
