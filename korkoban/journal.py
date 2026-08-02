"""The only module that touches `data/trade_journal.jsonl` — trade journal read/write."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path

from korkoban import guardrails

DEFAULT_JOURNAL_PATH: str = "data/trade_journal.jsonl"


@dataclass(frozen=True)
class TradeJournalEntry:
    entry_type: str  # "trade" | "trade_close" | "eod_note" | "scan_log"
    timestamp: str  # ISO-8601
    # Unique per logical trade, assigned when the position is opened (entry_type="trade").
    # A "trade_close" entry carries the same trade_id to resolve it without creating a second
    # "trade" — closing a position is not a new trade and must not count toward overtrading.
    trade_id: str | None = None
    symbol: str | None = None
    direction: str | None = None
    setup: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    size: int | None = None
    risk_dollars: float | None = None
    realized_r: float | None = None
    checklist_gate_answer: str | None = None
    counted_in_stats: bool | None = None
    reasoning: str | None = None  # free-text rationale for the trade (REQ-014)
    screenshot_path: str | None = None  # reference to a user-provided entry screenshot (REQ-014)
    # Optional scale/trail management plan (REQ-008) — populated from
    # korkoban.exits.compute_management_plan()'s return value, never hand-typed.
    scale_out_fraction: float | None = None
    scale_out_r_multiple: float | None = None
    trail_atr_multiple: float | None = None
    signal_found: bool | None = None  # for entry_type="scan_log" only
    note: str | None = None  # for entry_type="eod_note" only


def _append_line(path: str, entry: TradeJournalEntry) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def append_trade_entry(path: str, entry: TradeJournalEntry) -> TradeJournalEntry:
    gate_answer = guardrails.validate_checklist_gate_answer(entry.checklist_gate_answer)
    final_entry = replace(
        entry, trade_id=str(uuid.uuid4()), counted_in_stats=guardrails.counted_in_stats(gate_answer)
    )
    _append_line(path, final_entry)
    return final_entry


def append_trade_close(
    path: str, trade_id: str, realized_r: float, reasoning: str, timestamp: datetime
) -> TradeJournalEntry:
    """Resolves a previously-opened trade (by trade_id) without creating a new "trade" entry
    — closing a position is not a new trade and must not count toward overtrading."""
    entry = TradeJournalEntry(
        entry_type="trade_close",
        timestamp=timestamp.isoformat(),
        trade_id=trade_id,
        realized_r=realized_r,
        reasoning=reasoning,
    )
    _append_line(path, entry)
    return entry


def append_eod_note(path: str, day: date, note: str) -> TradeJournalEntry:
    day_iso = day.isoformat()
    for existing in read_all_entries(path):
        if existing.entry_type == "eod_note" and existing.timestamp.startswith(day_iso):
            raise ValueError(f"an eod_note already exists for {day_iso}")
    entry = TradeJournalEntry(entry_type="eod_note", timestamp=f"{day_iso}T00:00:00", note=note)
    _append_line(path, entry)
    return entry


def append_scan_log(path: str, timestamp: datetime, signal_found: bool) -> TradeJournalEntry:
    entry = TradeJournalEntry(
        entry_type="scan_log", timestamp=timestamp.isoformat(), signal_found=signal_found
    )
    _append_line(path, entry)
    return entry


def read_all_entries(path: str) -> list[TradeJournalEntry]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    entries: list[TradeJournalEntry] = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            entries.append(TradeJournalEntry(**json.loads(stripped)))
    return entries
