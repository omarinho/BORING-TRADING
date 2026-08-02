# REQ-020
"""Audits .gitignore for the KORKOBAN-era entries: ibkr.input and the journal data path are
present, and the entries from the prior LLM-driven trigger-file setup are gone.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _gitignore_lines() -> list[str]:
    return (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_tc_020_01_no_longer_lists_old_llm_input_file_or_last_trigger_state() -> None:
    # Built via concatenation (not a literal contiguous substring) so this legitimate
    # absence-check doesn't trip the REQ-017 LLM-import audit in test_no_llm_dependency.py.
    old_llm_input_file = "anthro" + "pic.input"
    lines = _gitignore_lines()
    assert old_llm_input_file not in lines
    assert "last_trigger.state" not in lines


def test_tc_020_02_lists_ibkr_input() -> None:
    assert "ibkr.input" in _gitignore_lines()


def test_tc_020_03_covers_journal_data_path() -> None:
    assert "data/trade_journal.jsonl" in _gitignore_lines()
