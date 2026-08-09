from __future__ import annotations

from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.errors import ApprovalError
from xt_aegis.models import ActionRequest, FileWriteAction, Provenance


def test_approval_can_be_decided_once(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state.db")
    request = ActionRequest(
        thread_id="thread.approval.1",
        action_id="action.approval",
        idempotency_key="approval-idempotency-0001",
        provenance=Provenance.OPERATOR,
        action=FileWriteAction(relative_path="sample/app.py", content="pass\n"),
    )
    store.start_run(request.thread_id, "safe_demo")
    approval_id = store.get_or_create_approval(request)
    assert not store.approval_is_valid(approval_id, request)
    store.decide_approval(approval_id, decision="approved", reviewer="alice")
    assert store.approval_is_valid(approval_id, request)
    with pytest.raises(ApprovalError, match="already decided"):
        store.decide_approval(approval_id, decision="denied", reviewer="bob")


def test_events_are_returned_in_order(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "state.db")
    store.append_event(trace_id="a", thread_id="thread.events", event_type="first", payload={"n": 1})
    store.append_event(trace_id="b", thread_id="thread.events", event_type="second", payload={"n": 2})
    events = store.list_events("thread.events")
    assert [event["event_type"] for event in events] == ["first", "second"]
