# REQ-013, REQ-014
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from korkoban.journal import (
    DEFAULT_JOURNAL_PATH,
    TradeJournalEntry,
    append_eod_note,
    append_scan_log,
    append_trade_close,
    append_trade_entry,
    read_all_entries,
)


def _trade_entry(**overrides: object) -> TradeJournalEntry:
    base: dict[str, object] = dict(
        entry_type="trade",
        timestamp="2026-01-05T10:00:00",
        symbol="ES",
        direction="long",
        setup="breakout",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        size=1,
        risk_dollars=500.0,
        realized_r=1.0,
        checklist_gate_answer="edge_based",
    )
    base.update(overrides)
    return TradeJournalEntry(**base)  # type: ignore[arg-type]


def test_tc_013_02_edge_based_answer_counted_in_stats_true(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    entry = _trade_entry(checklist_gate_answer="edge_based")
    persisted = append_trade_entry(path, entry)
    assert persisted.counted_in_stats is True


def test_tc_013_03_impulse_answer_persisted_but_excluded_from_stats(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    entry = _trade_entry(checklist_gate_answer="impulse", symbol="NQ")
    append_trade_entry(path, entry)
    all_entries = read_all_entries(path)
    assert len(all_entries) == 1
    assert all_entries[0].symbol == "NQ"
    assert all_entries[0].counted_in_stats is False


def test_tc_014_01_append_trade_entry_round_trips_all_fields(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    entry = _trade_entry()
    append_trade_entry(path, entry)
    entries = read_all_entries(path)
    assert len(entries) == 1
    got = entries[0]
    assert got.entry_type == "trade"
    assert got.symbol == "ES"
    assert got.direction == "long"
    assert got.setup == "breakout"
    assert got.entry_price == 100.0
    assert got.stop_price == 95.0
    assert got.target_price == 110.0
    assert got.size == 1
    assert got.risk_dollars == 500.0
    assert got.realized_r == 1.0
    assert got.checklist_gate_answer == "edge_based"
    assert got.counted_in_stats is True


def test_tc_014_02_append_eod_note_writes_entry(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    result = append_eod_note(path, day=date(2026, 1, 5), note="quiet day")
    assert result.entry_type == "eod_note"
    assert result.note == "quiet day"
    entries = read_all_entries(path)
    assert len(entries) == 1
    assert entries[0].entry_type == "eod_note"


def test_tc_014_03_second_eod_note_same_day_rejected(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    append_eod_note(path, day=date(2026, 1, 5), note="first note")
    with pytest.raises(ValueError):
        append_eod_note(path, day=date(2026, 1, 5), note="second note")


def test_tc_014_04_read_all_entries_reconstructs_trades_and_notes_with_no_data_loss(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "journal.jsonl")
    append_trade_entry(path, _trade_entry(symbol="ES", realized_r=1.0))
    append_trade_entry(path, _trade_entry(symbol="NQ", realized_r=-0.5))
    append_trade_entry(path, _trade_entry(symbol="CL", realized_r=2.0))
    append_eod_note(path, day=date(2026, 1, 5), note="note one")
    append_eod_note(path, day=date(2026, 1, 6), note="note two")

    entries = read_all_entries(path)
    trades = [e for e in entries if e.entry_type == "trade"]
    notes = [e for e in entries if e.entry_type == "eod_note"]
    assert len(trades) == 3
    assert len(notes) == 2
    assert [t.symbol for t in trades] == ["ES", "NQ", "CL"]
    assert [t.realized_r for t in trades] == [1.0, -0.5, 2.0]
    assert {n.note for n in notes} == {"note one", "note two"}


def test_tc_014_05_default_journal_path_is_relative_and_under_repo() -> None:
    path = Path(DEFAULT_JOURNAL_PATH)
    assert not path.is_absolute()
    assert DEFAULT_JOURNAL_PATH == "data/trade_journal.jsonl"


def test_append_scan_log_writes_scan_log_entry(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    result = append_scan_log(path, timestamp=datetime(2026, 1, 5, 16, 30, 0), signal_found=False)
    assert result.entry_type == "scan_log"
    assert result.signal_found is False
    entries = read_all_entries(path)
    assert len(entries) == 1
    assert entries[0].signal_found is False


def test_read_all_entries_returns_empty_list_when_file_missing(tmp_path: Path) -> None:
    path = str(tmp_path / "does_not_exist.jsonl")
    assert read_all_entries(path) == []


# REQ-008, REQ-014 (remediation round 1)
def test_trade_journal_entry_persists_management_plan_and_reasoning_fields(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "journal.jsonl")
    entry = _trade_entry(
        reasoning="clean breakout, matched every checklist condition",
        screenshot_path="screenshots/es_20260105.png",
        scale_out_fraction=0.5,
        scale_out_r_multiple=1.8,
        trail_atr_multiple=1.5,
    )
    append_trade_entry(path, entry)
    got = read_all_entries(path)[0]
    assert got.reasoning == "clean breakout, matched every checklist condition"
    assert got.screenshot_path == "screenshots/es_20260105.png"
    assert got.scale_out_fraction == 0.5
    assert got.scale_out_r_multiple == 1.8
    assert got.trail_atr_multiple == 1.5


def test_trade_journal_entry_management_plan_and_reasoning_default_to_none(
    tmp_path: Path,
) -> None:
    path = str(tmp_path / "journal.jsonl")
    entry = _trade_entry()
    append_trade_entry(path, entry)
    got = read_all_entries(path)[0]
    assert got.reasoning is None
    assert got.screenshot_path is None
    assert got.scale_out_fraction is None
    assert got.scale_out_r_multiple is None
    assert got.trail_atr_multiple is None


# ─── trade_id / journal-close (proper close mechanism, distinct from a "new trade") ─────────


def test_append_trade_entry_assigns_a_trade_id(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    persisted = append_trade_entry(path, _trade_entry())
    assert persisted.trade_id is not None
    assert isinstance(persisted.trade_id, str)
    assert persisted.trade_id != ""


def test_append_trade_entry_assigns_distinct_trade_ids(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    first = append_trade_entry(path, _trade_entry(symbol="ES"))
    second = append_trade_entry(path, _trade_entry(symbol="NQ"))
    assert first.trade_id != second.trade_id


def test_append_trade_close_writes_a_trade_close_entry(tmp_path: Path) -> None:
    path = str(tmp_path / "journal.jsonl")
    opened = append_trade_entry(path, _trade_entry(realized_r=None))
    assert opened.trade_id is not None

    closed = append_trade_close(
        path,
        trade_id=opened.trade_id,
        realized_r=1.5,
        reasoning="hit target",
        timestamp=datetime(2026, 1, 10, 16, 0, 0),
    )

    assert closed.entry_type == "trade_close"
    assert closed.trade_id == opened.trade_id
    assert closed.realized_r == 1.5
    assert closed.reasoning == "hit target"

    entries = read_all_entries(path)
    assert len(entries) == 2
    assert entries[0].entry_type == "trade"
    assert entries[1].entry_type == "trade_close"
