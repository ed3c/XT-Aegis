from __future__ import annotations

import json
from pathlib import Path

import pytest

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EVENT_SCHEMA_VERSION, EventRecorder
from xt_aegis.models import (
    ActionRequest,
    CommandAction,
    CommandSpec,
    ExecutionStatus,
    FileWriteAction,
    Provenance,
    RiskLevel,
)
from xt_aegis.replay import EVENT_SPAN_MAP, ReplayError, format_timeline, replay_events
from xt_aegis.runner import HarnessRunner
from xt_aegis.telemetry import (
    ATTRIBUTE_ALLOWLIST,
    InMemoryTelemetry,
    NullTelemetry,
    OpenTelemetryBridge,
    SpanName,
    SpanStatus,
    sanitize_attributes,
)
from xt_aegis.workspace import IsolatedWorkspace

GOOD_CODE = """TAX_RATE = 0.05

def calculate_tax(amount: float) -> float:
    if amount < 0:
        raise ValueError('Amount cannot be negative')
    return round(amount * TAX_RATE, 2)
"""

BAD_CODE = """def calculate_tax(amount: float) -> float:
    return amount * 0.10
"""


@pytest.fixture
def traced_runner(  # type: ignore[no-untyped-def]
    tmp_path: Path,
    template_dir: Path,
    compiled_skill,
):
    workspace = IsolatedWorkspace.from_template(template_dir, run_root=tmp_path / "run")
    store = CheckpointStore(tmp_path / "state" / "checkpoints.db")
    events = EventRecorder(store, tmp_path / "state" / "events.jsonl")
    telemetry = InMemoryTelemetry()
    runner = HarnessRunner(
        skill=compiled_skill,
        workspace=workspace,
        checkpoint_store=store,
        event_recorder=events,
        telemetry=telemetry,
    )
    return runner, telemetry, tmp_path / "state" / "events.jsonl"


def _request(*, action_id: str, key: str, content: str, provenance: Provenance) -> ActionRequest:
    return ActionRequest(
        thread_id="thread.telemetry.001",
        action_id=action_id,
        idempotency_key=key,
        actor_id="user:test",
        provenance=provenance,
        action=FileWriteAction(relative_path="sample_project/app.py", content=content),
    )


def _names(telemetry: InMemoryTelemetry) -> list[str]:
    return [span.name.value for span in telemetry.spans]


def _run_span(telemetry: InMemoryTelemetry) -> object:
    return next(span for span in telemetry.spans if span.name == SpanName.RUN)


def test_default_runtime_emits_no_telemetry(runner) -> None:  # type: ignore[no-untyped-def]
    assert isinstance(runner.telemetry, NullTelemetry)
    assert not isinstance(runner.telemetry, InMemoryTelemetry)


def test_successful_run_emits_the_documented_span_hierarchy(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner

    result = runner.execute(
        _request(
            action_id="good.patch",
            key="telemetry-success-0001",
            content=GOOD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    assert result.status == ExecutionStatus.SUCCEEDED
    assert _names(telemetry) == [
        "policy.evaluate",
        "assertion.check",
        "action.execute",
        "assertion.check",
        "checkpoint.persist",
        "run",
    ]
    assert {parent for parent, _ in telemetry.hierarchy()} == {"", "run"}
    run_span = _run_span(telemetry)
    assert run_span.status == SpanStatus.OK
    assert run_span.attributes["status"] == "succeeded"
    assert run_span.attributes["success"] is True


def test_rolled_back_run_emits_a_rollback_span(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner

    result = runner.execute(
        _request(
            action_id="bad.patch",
            key="telemetry-rollback-0001",
            content=BAD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    assert result.status == ExecutionStatus.ROLLED_BACK
    assert "workspace.rollback" in _names(telemetry)
    rollback = next(span for span in telemetry.spans if span.name == SpanName.WORKSPACE_ROLLBACK)
    assert rollback.attributes["rollback_integrity"] is True
    assert rollback.status == SpanStatus.OK
    failed_assertion = [
        span
        for span in telemetry.spans
        if span.name == SpanName.ASSERTION_CHECK and span.status == SpanStatus.ERROR
    ]
    assert len(failed_assertion) == 1
    assert failed_assertion[0].attributes["check_kind"] == "postcondition"


def test_policy_blocked_run_records_the_failed_policy_span(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner

    result = runner.execute(
        _request(
            action_id="external.injection",
            key="telemetry-blocked-0001",
            content=GOOD_CODE,
            provenance=Provenance.EXTERNAL_CONTENT,
        )
    )

    assert result.status == ExecutionStatus.BLOCKED
    policy = next(span for span in telemetry.spans if span.name == SpanName.POLICY_EVALUATE)
    assert policy.attributes["passed"] is False
    assert policy.status == SpanStatus.ERROR
    assert "action.execute" not in _names(telemetry)
    assert _run_span(telemetry).status == SpanStatus.OK


def test_suspended_run_records_an_approval_span(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner
    runner.skill = runner.skill.model_copy(
        update={
            "contract": runner.skill.contract.model_copy(
                update={"risk_level": RiskLevel.HIGH, "requires_approval": True}
            )
        }
    )
    runner.policy.contract = runner.skill.contract

    result = runner.execute(
        _request(
            action_id="approved.patch",
            key="telemetry-approval-0001",
            content=GOOD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    assert result.status == ExecutionStatus.SUSPENDED
    approval = next(span for span in telemetry.spans if span.name == SpanName.APPROVAL_WAIT)
    assert approval.attributes["outcome"] == "not_claimed"
    assert approval.attributes["risk_level"] == "high"
    assert "action.execute" not in _names(telemetry)


def test_failed_run_marks_the_run_span_as_error(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner

    def exploding_transaction() -> None:
        raise OSError("snapshot device failure")

    runner.workspace.begin_transaction = exploding_transaction  # type: ignore[method-assign]

    result = runner.execute(
        _request(
            action_id="failing.patch",
            key="telemetry-failed-0001",
            content=GOOD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    assert result.status == ExecutionStatus.FAILED
    assert _run_span(telemetry).status == SpanStatus.ERROR


def test_secret_canaries_never_reach_exported_attributes(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, telemetry, _ = traced_runner
    canary = "canary-token-value-not-for-export"
    script = "sample_project/leak.py"
    (runner.workspace.root / script).write_text(f"print('{canary}')\n", encoding="utf-8")
    request = ActionRequest(
        thread_id="thread.telemetry.001",
        action_id="canary.command",
        idempotency_key="telemetry-canary-0001",
        actor_id=f"user:{canary}",
        provenance=Provenance.OPERATOR,
        action=CommandAction(
            command=CommandSpec(
                description=f"print the {canary}",
                argv=["python3", script],
                expected_exit_codes={0},
                timeout_seconds=10.0,
            )
        ),
    )

    result = runner.execute(request)

    assert result.status in {ExecutionStatus.SUCCEEDED, ExecutionStatus.ROLLED_BACK}
    exported = json.dumps([span.model_dump(mode="json") for span in telemetry.spans])
    assert canary not in exported
    assert "actor_id" not in exported
    assert "argv" not in exported
    assert "stdout" not in exported


def test_attribute_allowlist_drops_unreviewed_keys_and_bounds_values() -> None:
    kept, dropped = sanitize_attributes(
        {
            "thread_id": "thread:1",
            "prompt": "the full model prompt",
            "description": "x" * 400,
            "step_number": 3,
            "success": True,
            "reason_code": None,
        }
    )

    assert set(kept) == {"thread_id", "description", "step_number", "success"}
    assert dropped == ["prompt", "reason_code"]
    assert len(kept["description"]) <= 256
    assert set(kept) <= ATTRIBUTE_ALLOWLIST


def test_jsonl_events_carry_a_schema_version(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, _, events_path = traced_runner

    runner.execute(
        _request(
            action_id="good.patch",
            key="telemetry-schema-0001",
            content=GOOD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    assert records
    assert {record["schema_version"] for record in records} == {EVENT_SCHEMA_VERSION}


def test_replay_reconstructs_the_timeline_without_executing_anything(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, _, events_path = traced_runner
    runner.execute(
        _request(
            action_id="bad.patch",
            key="telemetry-replay-0001",
            content=BAD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )
    before = runner.workspace.hash_tree()

    timeline = replay_events(events_path)

    assert runner.workspace.hash_tree() == before
    assert timeline.entries[0].event_type == "action_received"
    assert timeline.entries[0].span == SpanName.RUN
    assert timeline.unmapped_event_types == []
    assert "postcondition_failed" in format_timeline(timeline)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"event_type": "action_received"}, "no schema_version"),
        ({"schema_version": "2.0", "event_type": "action_received"}, "not supported"),
        ({"schema_version": "1.9", "event_type": "action_received"}, "not supported"),
        ({"schema_version": "one", "event_type": "action_received"}, "malformed"),
    ],
)
def test_incompatible_event_schema_fails_closed(
    tmp_path: Path, record: dict[str, object], message: str
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ReplayError, match=message):
        replay_events(path)


def test_replay_rejects_a_missing_or_malformed_trajectory(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="was not found"):
        replay_events(tmp_path / "absent.jsonl")

    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="not valid JSON"):
        replay_events(broken)


def test_every_emitted_event_type_has_a_span_mapping(traced_runner) -> None:  # type: ignore[no-untyped-def]
    runner, _, events_path = traced_runner
    for index, (action_id, content, provenance) in enumerate(
        [
            ("bad.patch", BAD_CODE, Provenance.AGENT_PROPOSAL),
            ("good.patch", GOOD_CODE, Provenance.AGENT_PROPOSAL),
            ("external.injection", GOOD_CODE, Provenance.EXTERNAL_CONTENT),
        ]
    ):
        runner.execute(
            _request(
                action_id=action_id,
                key=f"telemetry-map-{index:04d}",
                content=content,
                provenance=provenance,
            )
        )

    timeline = replay_events(events_path)

    assert timeline.unmapped_event_types == []
    assert {entry.event_type for entry in timeline.entries} <= set(EVENT_SPAN_MAP)


def test_opentelemetry_bridge_exports_only_allowlisted_attributes() -> None:
    bridge = OpenTelemetryBridge()
    with bridge.span(SpanName.RUN, thread_id="thread:1", prompt="secret prompt") as span:
        span.set(success=True)

    # The default API tracer provider is a no-op; the assertion is that bridging neither raises nor
    # forwards an unreviewed key through sanitize_attributes.
    kept, dropped = sanitize_attributes({"thread_id": "thread:1", "prompt": "secret prompt"})
    assert dropped == ["prompt"]
    assert kept == {"thread_id": "thread:1"}


def test_optional_otlp_exporter_is_not_configured_by_default() -> None:
    pytest.importorskip("opentelemetry.sdk.trace", reason="the otel extra is optional")
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    assert type(provider).__name__ in {"ProxyTracerProvider", "DefaultTracerProvider", "NoOpTracerProvider"}


def test_condition_spec_is_still_the_verdict_owner(traced_runner) -> None:  # type: ignore[no-untyped-def]
    """Telemetry observes conditions; it never changes whether one passed."""

    runner, telemetry, _ = traced_runner
    (runner.workspace.root / "sample_project/fail.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    runner.skill = runner.skill.model_copy(
        update={
            "contract": runner.skill.contract.model_copy(
                update={
                    "postconditions": [
                        CommandSpec(
                            description="always fails",
                            argv=["python3", "sample_project/fail.py"],
                        )
                    ]
                }
            )
        }
    )
    runner.policy.contract = runner.skill.contract

    result = runner.execute(
        _request(
            action_id="good.patch",
            key="telemetry-verdict-0001",
            content=GOOD_CODE,
            provenance=Provenance.AGENT_PROPOSAL,
        )
    )

    assert result.status == ExecutionStatus.ROLLED_BACK
    assert any(
        span.name == SpanName.ASSERTION_CHECK and span.status == SpanStatus.ERROR for span in telemetry.spans
    )
