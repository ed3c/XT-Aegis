"""Structured event emission to SQLite and JSONL."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from xt_aegis.checkpoint import CheckpointStore, utc_now

#: JSONL trajectory envelope version. The major component is a compatibility boundary: a reader accepts a
#: record whose major matches and whose minor is less than or equal to its own, and fails closed otherwise.
#: Adding an optional payload key is a minor change; removing or retyping one is a major change.
EVENT_SCHEMA_VERSION = "1.0"


class EventRecorder:
    def __init__(self, store: CheckpointStore, jsonl_path: str | Path | None = None) -> None:
        self.store = store
        self.jsonl_path = Path(jsonl_path).resolve() if jsonl_path is not None else None
        if self.jsonl_path is not None:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex

    def emit(
        self,
        *,
        trace_id: str,
        thread_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.store.append_event(
            trace_id=trace_id,
            thread_id=thread_id,
            event_type=event_type,
            payload=payload,
        )
        if self.jsonl_path is not None:
            record = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "trace_id": trace_id,
                "thread_id": thread_id,
                "event_type": event_type,
                "payload": payload,
                "created_at": utc_now(),
            }
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
