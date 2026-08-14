from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xt_aegis.controller import (
    ControllerBudgets,
    ControllerRunContext,
    ControllerStopReason,
    DiagnoseRepairController,
    ProviderAdmission,
)
from xt_aegis.controller_state import (
    STATE_SCHEMA_VERSION,
    ControllerStateError,
    ControllerStateRecord,
    ControllerStateStore,
    conditions_digest,
)
from xt_aegis.models import ActionRequest, ExecutionResult
from xt_aegis.proposals import (
    ProposalOutcome,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    ProviderUsage,
    SamplingProfile,
    TrustedEnvelopeConfig,
    TrustedRequestIds,
)

RUN_ID = "run:controller-state:0001"
TASK = "Replace the declared tax implementation."


def _profile() -> ProviderProfile:
    return ProviderProfile(
        provider="fake",
        model="deterministic",
        version="1.0",
        sampling=SamplingProfile(temperature=0.0, seed=7, context_tokens=8192, max_output_tokens=256),
    )


def _context() -> ControllerRunContext:
    return ControllerRunContext(
        source_commit="f" * 40,
        source_dirty=False,
        backend_profile="workspace-transaction:test",
        readiness_verdict=True,
    )


class CountingProvider:
    """Records every call so a test can assert that the provider was never reached."""

    def __init__(self, outcomes: list[ProposalOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[ProposalRequest] = []

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        self.calls.append(request)
        if not self._outcomes:
            raise AssertionError("the provider was called more times than the test declared")
        return self._outcomes.pop(0)


class RejectingExecutor:
    def execute(
        self, request: ActionRequest, *, timeout_seconds: float, max_output_bytes: int
    ) -> ExecutionResult:
        del timeout_seconds, max_output_bytes
        raise AssertionError(f"the executor must not receive {request.action_id}")


class FixedIdentitySource:
    def new_request_ids(self) -> TrustedRequestIds:
        return TrustedRequestIds(
            thread_id="thread:state",
            action_id="action:state",
            idempotency_key="idem:state:0001",
        )


def _refused_outcome(prompt: int = 10, completion: int = 5) -> ProposalOutcome:
    return ProposalOutcome(
        status=ProposalStatus.REFUSED,
        profile=_profile(),
        diagnostic="provider declined",
        usage=ProviderUsage(prompt_tokens=prompt, completion_tokens=completion),
    )


def _controller(  # type: ignore[no-untyped-def]
    compiled_skill,
    store: ControllerStateStore,
    provider: CountingProvider,
    *,
    budgets: ControllerBudgets | None = None,
    context: ControllerRunContext | None = None,
    admission: ProviderAdmission | None = None,
) -> DiagnoseRepairController:
    return DiagnoseRepairController(
        provider=provider,
        executor=RejectingExecutor(),
        skill=compiled_skill,
        trusted=TrustedEnvelopeConfig(target_path="sample_project/app.py"),
        context=context or _context(),
        budgets=budgets or ControllerBudgets(max_attempts=3),
        admission=admission,
        identity_source=FixedIdentitySource(),
        state_store=store,
    )


@pytest.fixture
def store(tmp_path: Path) -> ControllerStateStore:
    return ControllerStateStore(tmp_path / "state" / "controller.db")


def test_a_completed_run_persists_totals_and_a_terminal_reason(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    provider = CountingProvider([_refused_outcome(prompt=11, completion=4)])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert result.stop_reason == ControllerStopReason.PROPOSAL_REJECTED
    record = store.load(RUN_ID)
    assert record is not None
    assert record.total_prompt_tokens == 11
    assert record.total_completion_tokens == 4
    assert record.in_flight_attempt is None
    assert record.terminal_stop_reason == "proposal_rejected"


def test_a_terminal_run_is_not_resumed(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    first = CountingProvider([_refused_outcome()])
    _controller(compiled_skill, store, first).run(task=TASK, run_id=RUN_ID)

    second = CountingProvider([_refused_outcome()])
    result = _controller(compiled_skill, store, second).run(task=TASK, run_id=RUN_ID)

    assert second.calls == []
    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED
    assert "already reached the terminal state" in result.diagnostic


def _persist(store: ControllerStateStore, **overrides: object) -> None:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "conditions_digest": conditions_digest(
            task=TASK,
            context=_context(),
            budgets=ControllerBudgets(max_attempts=3),
            admission=None,
        ),
        "next_attempt_number": 2,
        "total_prompt_tokens": 40,
        "total_completion_tokens": 20,
        "repair_task": f"{TASK}\n\nRepair attempt 2.",
    }
    values.update(overrides)
    store.save(ControllerStateRecord(**values))  # type: ignore[arg-type]


def test_a_matching_restart_resumes_totals_and_the_attempt_number(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(store)
    provider = CountingProvider([_refused_outcome(prompt=7, completion=3)])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert len(provider.calls) == 1
    assert result.attempts[0].attempt_number == 2
    assert result.total_prompt_tokens == 47
    assert result.total_completion_tokens == 23
    assert provider.calls[0].task.endswith("Repair attempt 2.")


def test_a_stale_state_schema_version_fails_closed(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(store)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE controller_runs SET schema_version = '0.9' WHERE run_id = ?", (RUN_ID,))
    provider = CountingProvider([_refused_outcome()])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED
    assert STATE_SCHEMA_VERSION in result.diagnostic


def test_an_unreadable_record_fails_closed(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(store)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE controller_runs SET record_json = '{' WHERE run_id = ?", (RUN_ID,))
    provider = CountingProvider([_refused_outcome()])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED


def test_an_in_flight_attempt_fails_closed(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(store, in_flight_attempt=2)
    provider = CountingProvider([_refused_outcome()])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED
    assert "workspace outcome is unknown" in result.diagnostic


@pytest.mark.parametrize(
    "changed",
    ["task", "context", "budgets", "admission"],
    ids=lambda value: f"changed-{value}",
)
def test_a_changed_condition_fails_closed_without_a_provider_call(  # type: ignore[no-untyped-def]
    store,
    compiled_skill,
    changed: str,
) -> None:
    _persist(store)
    provider = CountingProvider([_refused_outcome()])
    task = "A different task." if changed == "task" else TASK
    context = _context().model_copy(update={"source_dirty": True}) if changed == "context" else _context()
    budgets = ControllerBudgets(max_attempts=4) if changed == "budgets" else ControllerBudgets(max_attempts=3)
    admission = (
        ProviderAdmission(provider="fake", model="deterministic", version="1.0")
        if changed == "admission"
        else None
    )

    result = _controller(
        compiled_skill,
        store,
        provider,
        budgets=budgets,
        context=context,
        admission=admission,
    ).run(task=task, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.RECOVERY_FAILED
    assert "changed since this run was persisted" in result.diagnostic


def test_a_refused_resume_does_not_overwrite_the_state_it_refused(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(store, in_flight_attempt=2)
    before = store.load(RUN_ID)
    provider = CountingProvider([_refused_outcome()])

    _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert store.load(RUN_ID) == before


def test_a_resumed_run_stops_on_the_carried_attempt_budget(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    _persist(
        store,
        next_attempt_number=4,
        conditions_digest=conditions_digest(
            task=TASK,
            context=_context(),
            budgets=ControllerBudgets(max_attempts=3),
            admission=None,
        ),
    )
    provider = CountingProvider([_refused_outcome()])

    result = _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert "before resume" in result.diagnostic


def test_a_resumed_run_stops_on_the_carried_token_budget(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    budgets = ControllerBudgets(max_attempts=3, max_prompt_tokens=50, max_completion_tokens=50)
    _persist(
        store,
        total_prompt_tokens=50,
        total_completion_tokens=10,
        conditions_digest=conditions_digest(task=TASK, context=_context(), budgets=budgets, admission=None),
    )
    provider = CountingProvider([_refused_outcome()])

    result = _controller(compiled_skill, store, provider, budgets=budgets).run(task=TASK, run_id=RUN_ID)

    assert provider.calls == []
    assert result.stop_reason == ControllerStopReason.BUDGET_EXHAUSTED
    assert "prompt token budget cannot cover the next call" in result.diagnostic


def test_a_run_without_an_identifier_persists_nothing(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    provider = CountingProvider([_refused_outcome()])

    _controller(compiled_skill, store, provider).run(task=TASK)

    assert store.load(RUN_ID) is None


def test_the_state_store_round_trips_and_rejects_an_unsupported_schema(tmp_path: Path) -> None:
    store = ControllerStateStore(tmp_path / "controller.db")
    record = ControllerStateRecord(
        run_id="run:roundtrip",
        conditions_digest="a" * 64,
        next_attempt_number=2,
        total_prompt_tokens=1,
        total_completion_tokens=2,
    )

    store.save(record)
    assert store.load("run:roundtrip") == record
    assert store.load("run:absent") is None

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("UPDATE controller_runs SET schema_version = '2.0'")
    with pytest.raises(ControllerStateError, match="is not supported"):
        store.load("run:roundtrip")


def test_the_conditions_digest_covers_every_declared_input() -> None:
    base = conditions_digest(
        task=TASK, context=_context(), budgets=ControllerBudgets(max_attempts=3), admission=None
    )

    assert (
        conditions_digest(
            task="other", context=_context(), budgets=ControllerBudgets(max_attempts=3), admission=None
        )
        != base
    )
    assert (
        conditions_digest(
            task=TASK,
            context=_context().model_copy(update={"backend_profile": "other"}),
            budgets=ControllerBudgets(max_attempts=3),
            admission=None,
        )
        != base
    )
    assert (
        conditions_digest(
            task=TASK, context=_context(), budgets=ControllerBudgets(max_attempts=9), admission=None
        )
        != base
    )
    assert (
        conditions_digest(
            task=TASK,
            context=_context(),
            budgets=ControllerBudgets(max_attempts=3),
            admission=ProviderAdmission(provider="fake", model="deterministic", version="1.0"),
        )
        != base
    )


def test_a_repaired_attempt_persists_its_repair_task(store, compiled_skill) -> None:  # type: ignore[no-untyped-def]
    """A resume must continue with the repair context, not with the original task."""

    _persist(store, repair_task=f"{TASK}\n\nRepair attempt 2. Prior execution_failed: boom")
    provider = CountingProvider([_refused_outcome()])

    _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert "Prior execution_failed: boom" in provider.calls[0].task


def test_a_ready_proposal_marks_the_attempt_in_flight_before_the_provider_answers(  # type: ignore[no-untyped-def]
    store,
    compiled_skill,
) -> None:
    observed: list[int | None] = []

    class ObservingProvider(CountingProvider):
        def propose(self, request: ProposalRequest) -> ProposalOutcome:
            record = store.load(RUN_ID)
            observed.append(record.in_flight_attempt if record is not None else None)
            return super().propose(request)

    provider = ObservingProvider(
        [
            ProposalOutcome(
                status=ProposalStatus.MALFORMED,
                profile=_profile(),
                diagnostic="unusable",
                usage=ProviderUsage(prompt_tokens=1, completion_tokens=1),
            )
        ]
    )

    _controller(compiled_skill, store, provider).run(task=TASK, run_id=RUN_ID)

    assert observed == [1]
    assert (record := store.load(RUN_ID)) is not None and record.in_flight_attempt is None
