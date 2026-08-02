# REQ-017
"""KORKOBAN is a rule-based system with zero LLM/AI SDK dependency — audit the whole repo
source (and pyproject.toml) for any such import or dependency string.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve()

LLM_SUBSTRINGS = ("openai", "anthropic", "langchain", "transformers", "llama")


def _audited_py_files() -> list[Path]:
    files = list((REPO_ROOT / "korkoban").rglob("*.py")) + list((REPO_ROOT / "tests").rglob("*.py"))
    return [f for f in files if f.resolve() != THIS_FILE and "__pycache__" not in f.parts]


def test_tc_017_01_no_llm_ai_sdk_import_anywhere() -> None:
    for py_file in _audited_py_files():
        source = py_file.read_text(encoding="utf-8").lower()
        for banned in LLM_SUBSTRINGS:
            assert banned not in source, f"{banned!r} found in {py_file.relative_to(REPO_ROOT)}"

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for banned in LLM_SUBSTRINGS:
        assert banned not in pyproject, f"{banned!r} found in pyproject.toml"
