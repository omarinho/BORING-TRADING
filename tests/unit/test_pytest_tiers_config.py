# REQ-018
"""Verifies the two test tiers stay cleanly separated: no tests/unit/ test carries the
integration marker, the marker is registered so pytest never warns about it, and every
tests/integration/ test function does carry the marker.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_DIR = REPO_ROOT / "tests" / "unit"
INTEGRATION_DIR = REPO_ROOT / "tests" / "integration"
THIS_FILE = Path(__file__).resolve()


def test_tc_018_01_no_unit_test_carries_the_integration_marker() -> None:
    # Static-grep approach (rather than spawning a nested pytest --collect-only process from
    # inside a test): tests/unit/ must never contain the integration marker string at all.
    # This file itself is excluded — it necessarily contains the marker string as a literal
    # to search for, same reasoning as the self-exclusion in test_no_llm_dependency.py.
    for py_file in UNIT_DIR.glob("*.py"):
        if py_file.resolve() == THIS_FILE:
            continue
        source = py_file.read_text(encoding="utf-8")
        assert "pytest.mark.integration" not in source, f"{py_file.name} carries the marker"


def test_tc_018_03_integration_marker_is_registered() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.pytest.ini_options]" in pyproject
    assert "integration:" in pyproject


def test_tc_018_04_every_integration_test_function_is_marked() -> None:
    if not INTEGRATION_DIR.exists():
        return
    for py_file in INTEGRATION_DIR.glob("*.py"):
        lines = py_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("def test_"):
                continue
            marked = False
            j = i - 1
            while j >= 0 and lines[j].strip().startswith("@"):
                if "pytest.mark.integration" in lines[j]:
                    marked = True
                j -= 1
            assert marked, f"{py_file.name}:{i + 1} test function missing @pytest.mark.integration"
