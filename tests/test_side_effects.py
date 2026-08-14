from __future__ import annotations

from pathlib import Path

import pytest

from xt_aegis.side_effects import (
    AmbiguousEffect,
    EffectIdentity,
    EffectOutcome,
    EffectState,
    EffectStore,
    ProtectedEffectRunner,
    argument_digest,
)


def _identity(**overrides: object) -> EffectIdentity:
    values: dict[str, object] = {
        "subject": "user:alice",
        "tool": "synthetic-deployer",
        "resource": "service:checkout",
        "policy_version": "1.0",
        "logical_operation_id": "deploy-2026-08-14-a",
        "argument_digest": argument_digest({"revision": "abc123"}),
    }
    values.update(overrides)
    return EffectIdentity(**values)  # type: ignore[arg-type]


class SyntheticAdapter:
    """A fake provider. No test in this file touches a real external service."""

    def __init__(
        self,
        *,
        outcomes: list[EffectOutcome | Exception] | None = None,
        supports_idempotency_key: bool = True,
        supports_reconciliation: bool = True,
        reconcile_result: EffectOutcome | None = None,
    ) -> None:
        self.supports_idempotency_key = supports_idempotency_key
        self.supports_reconciliation = supports_reconciliation
        self._outcomes = list(outcomes or [])
        self._reconcile_result = reconcile_result
        self.dispatched: list[str | None] = []
        self.reconciled: list[str] = []

    def dispatch(self, identity: EffectIdentity, *, idempotency_key: str | None) -> EffectOutcome:
        del identity
        self.dispatched.append(idempotency_key)
        if not self._outcomes:
            raise AssertionError("the adapter was dispatched more times than the test declared")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def reconcile(self, identity: EffectIdentity, *, idempotency_key: str) -> EffectOutcome | None:
        del identity
        self.reconciled.append(idempotency_key)
        return self._reconcile_result


def _committed(reference: str = "provider-ref-1") -> EffectOutcome:
    return EffectOutcome(
        state=EffectState.COMMITTED, provider_reference=reference, receipt="accepted", reason="ok"
    )


@pytest.fixture
def runner(tmp_path: Path) -> ProtectedEffectRunner:
    return ProtectedEffectRunner(EffectStore(tmp_path / "effects.db"))


def test_a_committed_effect_is_never_dispatched_twice(runner: ProtectedEffectRunner) -> None:
    adapter = SyntheticAdapter(outcomes=[_committed()])
    identity = _identity()

    first = runner.execute(identity, adapter)
    second = runner.execute(identity, adapter)

    assert first.state is EffectState.COMMITTED
    assert second == first
    assert len(adapter.dispatched) == 1
    assert adapter.dispatched[0] == identity.idempotency_key()


def test_a_timeout_after_the_provider_committed_leaves_an_unknown_record(
    runner: ProtectedEffectRunner,
) -> None:
    adapter = SyntheticAdapter(outcomes=[TimeoutError("no acknowledgement")], reconcile_result=None)

    record = runner.execute(_identity(), adapter)

    assert record.state is EffectState.UNKNOWN
    assert "timed out" in record.reason
    assert record.needs_reconciliation


def test_reconciliation_resolves_an_unknown_record_to_committed(runner: ProtectedEffectRunner) -> None:
    identity = _identity()
    timing_out = SyntheticAdapter(outcomes=[TimeoutError("no acknowledgement")])
    runner.execute(identity, timing_out)

    resolver = SyntheticAdapter(reconcile_result=_committed("provider-ref-late"))
    resolved = runner.reconcile(identity, resolver)

    assert resolved is not None
    assert resolved.state is EffectState.COMMITTED
    assert resolved.provider_reference == "provider-ref-late"
    assert resolver.dispatched == []


def test_an_unknown_record_is_never_retried_by_execute(runner: ProtectedEffectRunner) -> None:
    identity = _identity()
    runner.execute(identity, SyntheticAdapter(outcomes=[TimeoutError("lost")]))

    blocked = SyntheticAdapter(outcomes=[_committed()], reconcile_result=None)
    with pytest.raises(AmbiguousEffect, match="unknown"):
        runner.execute(identity, blocked)

    assert blocked.dispatched == []


def test_an_adapter_without_reconciliation_leaves_the_record_unknown_and_says_so(
    runner: ProtectedEffectRunner,
) -> None:
    identity = _identity()
    runner.execute(identity, SyntheticAdapter(outcomes=[TimeoutError("lost")]))

    weak = SyntheticAdapter(supports_reconciliation=False)
    resolved = runner.reconcile(identity, weak)

    assert resolved is not None
    assert resolved.state is EffectState.UNKNOWN
    assert "cannot look this operation up" in resolved.reason
    assert weak.reconciled == []


def test_intent_is_persisted_before_dispatch(tmp_path: Path) -> None:
    """A crash between persisting intent and dispatching must leave a record, not silence."""

    store = EffectStore(tmp_path / "effects.db")
    runner = ProtectedEffectRunner(store)
    identity = _identity()
    observed: list[str] = []

    class CrashingAdapter(SyntheticAdapter):
        def dispatch(self, identity: EffectIdentity, *, idempotency_key: str | None) -> EffectOutcome:
            record = store.read(identity.idempotency_key())
            observed.append(record.state.value if record is not None else "missing")
            raise RuntimeError("process died mid-call")

    record = runner.execute(identity, CrashingAdapter(outcomes=[_committed()]))

    assert observed == ["pending"]
    assert record.state is EffectState.UNKNOWN
    assert store.read(identity.idempotency_key()) is not None


def test_a_definite_failure_is_retryable(runner: ProtectedEffectRunner) -> None:
    identity = _identity()
    failing = SyntheticAdapter(
        outcomes=[EffectOutcome(state=EffectState.FAILED, reason="provider rejected the request")]
    )
    first = runner.execute(identity, failing)
    assert first.state is EffectState.FAILED

    retrying = SyntheticAdapter(outcomes=[_committed()])
    second = runner.execute(identity, retrying)

    assert second.state is EffectState.COMMITTED
    assert second.attempts == 2
    assert len(retrying.dispatched) == 1


@pytest.mark.parametrize(
    "field",
    ["subject", "tool", "resource", "policy_version", "logical_operation_id", "argument_digest"],
)
def test_every_identity_component_participates_in_the_key(field: str) -> None:
    base = _identity()
    changed = (
        _identity(argument_digest=argument_digest({"revision": "different"}))
        if field == "argument_digest"
        else _identity(**{field: "changed-value"})
    )

    assert base.idempotency_key() != changed.idempotency_key()


def test_the_same_identity_always_produces_the_same_key() -> None:
    assert _identity().idempotency_key() == _identity().idempotency_key()
    assert argument_digest({"a": 1, "b": 2}) == argument_digest({"b": 2, "a": 1})


def test_receipts_are_redacted_before_they_are_stored(runner: ProtectedEffectRunner) -> None:
    adapter = SyntheticAdapter(
        outcomes=[
            EffectOutcome(
                state=EffectState.COMMITTED,
                receipt="api_key=secret-value-not-for-storage accepted",
                reason="ok",
            )
        ]
    )

    record = runner.execute(_identity(), adapter)

    assert "secret-value-not-for-storage" not in record.receipt
    assert "[REDACTED]" in record.receipt
    assert len(record.receipt) <= 4_096


def test_an_oversized_receipt_cannot_be_constructed_at_all() -> None:
    """The bound is a type boundary, not a runtime truncation an adapter could route around."""

    with pytest.raises(ValueError, match="at most 4096 characters"):
        EffectOutcome(state=EffectState.COMMITTED, receipt="x" * 8_000)


def test_an_adapter_without_idempotency_support_receives_no_key(runner: ProtectedEffectRunner) -> None:
    adapter = SyntheticAdapter(outcomes=[_committed()], supports_idempotency_key=False)

    runner.execute(_identity(), adapter)

    assert adapter.dispatched == [None]


def test_reconciling_an_unknown_operation_returns_nothing(runner: ProtectedEffectRunner) -> None:
    assert runner.reconcile(_identity(), SyntheticAdapter()) is None


def test_reconciling_a_committed_record_does_not_call_the_adapter(runner: ProtectedEffectRunner) -> None:
    identity = _identity()
    runner.execute(identity, SyntheticAdapter(outcomes=[_committed()]))

    resolver = SyntheticAdapter()
    record = runner.reconcile(identity, resolver)

    assert record is not None
    assert record.state is EffectState.COMMITTED
    assert resolver.reconciled == []


def test_reconciliation_that_cannot_decide_keeps_the_record_unknown(
    runner: ProtectedEffectRunner,
) -> None:
    identity = _identity()
    runner.execute(identity, SyntheticAdapter(outcomes=[TimeoutError("lost")]))

    undecided = SyntheticAdapter(reconcile_result=None)
    record = runner.reconcile(identity, undecided)

    assert record is not None
    assert record.state is EffectState.UNKNOWN
    assert "could not determine" in record.reason
    assert undecided.reconciled == [identity.idempotency_key()]


def test_two_different_operations_do_not_share_a_record(runner: ProtectedEffectRunner) -> None:
    first = _identity(logical_operation_id="deploy-one")
    second = _identity(logical_operation_id="deploy-two")

    runner.execute(first, SyntheticAdapter(outcomes=[_committed("ref-one")]))
    record = runner.execute(second, SyntheticAdapter(outcomes=[_committed("ref-two")]))

    assert record.provider_reference == "ref-two"
    assert runner.store.read(first.idempotency_key()).provider_reference == "ref-one"  # type: ignore[union-attr]
