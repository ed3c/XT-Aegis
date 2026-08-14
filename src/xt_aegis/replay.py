"""Reconstruct an execution timeline from persisted events without a model or a tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.events import EVENT_SCHEMA_VERSION
from xt_aegis.telemetry import ATTRIBUTE_ALLOWLIST, SpanName

#: Persisted event type -> the span it belongs to. This is the deterministic mapping that lets a
#: trajectory be re-read as a trace after the fact, with no model context and no re-execution.
EVENT_SPAN_MAP: dict[str, SpanName] = {
    "action_received": SpanName.RUN,
    "idempotent_replay": SpanName.RUN,
    "identity_conflict": SpanName.CHECKPOINT_PERSIST,
    "policy_blocked": SpanName.POLICY_EVALUATE,
    "budget_blocked": SpanName.POLICY_EVALUATE,
    "approval_required": SpanName.APPROVAL_WAIT,
    "approval_denied": SpanName.APPROVAL_WAIT,
    "precondition_checked": SpanName.ASSERTION_CHECK,
    "postcondition_checked": SpanName.ASSERTION_CHECK,
    "precondition_failed": SpanName.WORKSPACE_ROLLBACK,
    "postcondition_failed": SpanName.WORKSPACE_ROLLBACK,
    "action_failed": SpanName.WORKSPACE_ROLLBACK,
    "executor_exception": SpanName.WORKSPACE_ROLLBACK,
    "action_succeeded": SpanName.CHECKPOINT_PERSIST,
}


class ReplayError(ValueError):
    """Raised when a trajectory cannot be read under the supported schema contract."""


class ReplayEntry(BaseModel):
    """One event projected onto the span vocabulary, with only allowlisted payload keys retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    created_at: str = Field(max_length=64)
    trace_id: str = Field(max_length=64)
    thread_id: str = Field(max_length=128)
    event_type: str = Field(max_length=64)
    span: SpanName | None = None
    attributes: dict[str, str | int | bool] = Field(default_factory=dict)


class ReplayTimeline(BaseModel):
    """Deterministic projection of one trajectory file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = EVENT_SCHEMA_VERSION
    source: str = Field(max_length=1_024)
    entries: list[ReplayEntry] = Field(max_length=100_000)
    unmapped_event_types: list[str] = Field(default_factory=list, max_length=64)


def _assert_compatible(record_version: object, line_number: int) -> None:
    if record_version is None:
        raise ReplayError(f"line {line_number}: event has no schema_version and cannot be replayed safely")
    if not isinstance(record_version, str):
        raise ReplayError(f"line {line_number}: schema_version must be a string")
    try:
        major, minor = (int(part) for part in record_version.split(".", 1))
        supported_major, supported_minor = (int(part) for part in EVENT_SCHEMA_VERSION.split(".", 1))
    except ValueError as exc:
        raise ReplayError(f"line {line_number}: malformed schema_version {record_version!r}") from exc
    if major != supported_major or minor > supported_minor:
        raise ReplayError(
            f"line {line_number}: event schema {record_version} is not supported by {EVENT_SCHEMA_VERSION}"
        )


def _attributes(payload: object) -> dict[str, str | int | bool]:
    if not isinstance(payload, dict):
        return {}
    kept: dict[str, str | int | bool] = {}
    for key, value in payload.items():
        if key not in ATTRIBUTE_ALLOWLIST or value is None:
            continue
        kept[key] = value if isinstance(value, bool | int) else str(value)[:256]
    return kept


def replay_events(path: str | Path) -> ReplayTimeline:
    """Read a JSONL trajectory and return its timeline; nothing is executed and no model is called."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReplayError(f"trajectory file was not found: {source}")
    entries: list[ReplayEntry] = []
    unmapped: set[str] = set()
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplayError(f"line {line_number}: trajectory record is not valid JSON") from exc
        if not isinstance(record, dict):
            raise ReplayError(f"line {line_number}: trajectory record must be an object")
        _assert_compatible(record.get("schema_version"), line_number)
        event_type = str(record.get("event_type", ""))
        span = EVENT_SPAN_MAP.get(event_type)
        if span is None:
            unmapped.add(event_type)
        entries.append(
            ReplayEntry(
                sequence=len(entries) + 1,
                created_at=str(record.get("created_at", ""))[:64],
                trace_id=str(record.get("trace_id", ""))[:64],
                thread_id=str(record.get("thread_id", ""))[:128],
                event_type=event_type[:64],
                span=span,
                attributes=_attributes(record.get("payload")),
            )
        )
    return ReplayTimeline(source=str(source), entries=entries, unmapped_event_types=sorted(unmapped))


def format_timeline(timeline: ReplayTimeline) -> str:
    """Render the timeline as one line per event so a reviewer can read it without tooling."""

    lines = [f"trajectory: {timeline.source}", f"events: {len(timeline.entries)}", ""]
    for entry in timeline.entries:
        span = entry.span.value if entry.span is not None else "-"
        attributes = " ".join(f"{key}={value}" for key, value in sorted(entry.attributes.items()))
        lines.append(f"{entry.sequence:>4}  {entry.created_at}  {span:<20}{entry.event_type:<24}{attributes}")
    if timeline.unmapped_event_types:
        lines.extend(["", f"unmapped event types: {', '.join(timeline.unmapped_event_types)}"])
    return "\n".join(lines)
