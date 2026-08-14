from __future__ import annotations

import pytest

from xt_aegis.mcp_authorization import (
    AdmissionDecision,
    DenyReason,
    MutatingToolAdmission,
    ProtectionProfile,
    SubjectAssertion,
    ToolApproval,
)

DIGEST = "a" * 64
NOW = 1_000.0
TOOL = "apply_patch"


def _profile(**overrides: bool) -> ProtectionProfile:
    values = {
        "isolation_ready": True,
        "egress_ready": True,
        "credential_broker_ready": True,
        "approval_ready": True,
        "audit_ready": True,
    }
    values.update(overrides)
    return ProtectionProfile(**values)  # type: ignore[arg-type]


def _assertion(**overrides: object) -> SubjectAssertion:
    values: dict[str, object] = {
        "subject": "user:alice",
        "issuer": "https://issuer.invalid",
        "audience": "xt-aegis-local",
        "expires_at_epoch": NOW + 300,
        "nonce": "nonce-00000001",
        "scopes": frozenset({"mutate:workspace"}),
    }
    values.update(overrides)
    return SubjectAssertion(**values)  # type: ignore[arg-type]


def _approval(**overrides: object) -> ToolApproval:
    values: dict[str, object] = {
        "approval_id": "approval-1",
        "subject": "user:alice",
        "tool": TOOL,
        "action_digest": DIGEST,
        "policy_version": "1.0",
        "reason": "reviewed by the operator",
        "expires_at_epoch": NOW + 300,
    }
    values.update(overrides)
    return ToolApproval(**values)  # type: ignore[arg-type]


def _admission(**overrides: object) -> MutatingToolAdmission:
    values: dict[str, object] = {
        "profile": _profile(),
        "trusted_issuer": "https://issuer.invalid",
        "expected_audience": "xt-aegis-local",
        "tool_scopes": {TOOL: frozenset({"mutate:workspace"})},
        "clock": lambda: NOW,
    }
    values.update(overrides)
    return MutatingToolAdmission(**values)  # type: ignore[arg-type]


#: Distinguishes "the caller did not override the approval" from "the caller passed no approval". Without
#: it, a test asking for the no-approval path would silently be handed a valid one.
_DEFAULT = object()


def _admit(
    admission: MutatingToolAdmission,
    *,
    request_id: str = "request-1",
    tool: str = TOOL,
    assertion: SubjectAssertion | None = None,
    action_digest: str = DIGEST,
    policy_version: str = "1.0",
    approval: ToolApproval | object | None = _DEFAULT,
) -> AdmissionDecision:
    resolved = _approval() if approval is _DEFAULT else approval
    return admission.admit(
        request_id=request_id,
        tool=tool,
        assertion=assertion or _assertion(),
        action_digest=action_digest,
        policy_version=policy_version,
        approval=resolved,  # type: ignore[arg-type]
    )


def test_the_happy_path_admits_exactly_once() -> None:
    admission = _admission()

    decision = _admit(admission)

    assert decision.admitted is True
    assert decision.reason is None
    assert "approval-1" in decision.detail


@pytest.mark.parametrize(
    "absent",
    ["isolation_ready", "egress_ready", "credential_broker_ready", "approval_ready", "audit_ready"],
)
def test_an_incomplete_protection_profile_denies_first(absent: str) -> None:
    admission = _admission(profile=_profile(**{absent: False}))

    # Everything else about this call is invalid too; the profile must still be the reported reason.
    decision = _admit(
        admission,
        assertion=_assertion(issuer="https://attacker.invalid", expires_at_epoch=NOW - 1),
        approval=None,
    )

    assert decision.admitted is False
    assert decision.reason is DenyReason.PROTECTION_UNAVAILABLE
    assert absent in decision.detail


def test_a_profile_defaults_to_nothing_available() -> None:
    assert ProtectionProfile().missing() == [
        "approval_ready",
        "audit_ready",
        "credential_broker_ready",
        "egress_ready",
        "isolation_ready",
    ]


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"expires_at_epoch": NOW - 1}, DenyReason.ASSERTION_EXPIRED),
        ({"expires_at_epoch": NOW}, DenyReason.ASSERTION_EXPIRED),
        ({"issuer": "https://attacker.invalid"}, DenyReason.ISSUER_NOT_TRUSTED),
        ({"audience": "another-server"}, DenyReason.AUDIENCE_MISMATCH),
    ],
)
def test_an_invalid_assertion_is_denied_with_its_own_reason(
    overrides: dict[str, object], reason: DenyReason
) -> None:
    decision = _admit(_admission(), assertion=_assertion(**overrides))

    assert decision.admitted is False
    assert decision.reason is reason


def test_a_replayed_nonce_is_denied_even_when_everything_else_is_valid() -> None:
    admission = _admission()
    assert _admit(admission, request_id="request-1").admitted is True

    replay = _admit(
        admission,
        request_id="request-2",
        approval=_approval(approval_id="approval-2"),
    )

    assert replay.admitted is False
    assert replay.reason is DenyReason.NONCE_REPLAYED


def test_an_undeclared_tool_is_denied_rather_than_defaulting_to_allowed() -> None:
    admission = _admission()

    decision = _admit(admission, tool="delete_everything", approval=_approval(tool="delete_everything"))

    assert decision.admitted is False
    assert decision.reason is DenyReason.TOOL_NOT_DECLARED
    assert admission.declared_tools == (TOOL,)


def test_a_missing_scope_is_denied() -> None:
    decision = _admit(_admission(), assertion=_assertion(scopes=frozenset({"read:evidence"})))

    assert decision.admitted is False
    assert decision.reason is DenyReason.SCOPE_MISSING
    assert "mutate:workspace" in decision.detail


def test_extra_scopes_do_not_grant_an_undeclared_tool() -> None:
    admission = _admission()

    decision = _admit(
        admission,
        tool="unlisted_tool",
        assertion=_assertion(scopes=frozenset({"mutate:workspace", "admin:everything"})),
        approval=_approval(tool="unlisted_tool"),
    )

    assert decision.reason is DenyReason.TOOL_NOT_DECLARED


def test_a_mutating_call_without_an_approval_is_denied() -> None:
    decision = _admit(_admission(), approval=None)

    assert decision.admitted is False
    assert decision.reason is DenyReason.APPROVAL_MISSING


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject": "user:mallory"},
        {"tool": "another_tool"},
        {"action_digest": "b" * 64},
        {"policy_version": "2.0"},
    ],
    ids=lambda value: str(value),
)
def test_an_approval_that_does_not_cover_this_call_is_denied(overrides: dict[str, object]) -> None:
    decision = _admit(_admission(), approval=_approval(**overrides))

    assert decision.admitted is False
    assert decision.reason is DenyReason.APPROVAL_MISMATCH


def test_argument_substitution_after_approval_is_denied() -> None:
    """The approval covers one action digest; a different payload is a different call."""

    decision = _admit(_admission(), action_digest="c" * 64)

    assert decision.admitted is False
    assert decision.reason is DenyReason.APPROVAL_MISMATCH
    assert "action_digest" in decision.detail


def test_an_expired_approval_is_denied() -> None:
    decision = _admit(_admission(), approval=_approval(expires_at_epoch=NOW - 1))

    assert decision.admitted is False
    assert decision.reason is DenyReason.APPROVAL_EXPIRED


def test_an_approval_cannot_be_used_twice() -> None:
    admission = _admission()
    assert _admit(admission, request_id="request-1").admitted is True

    reuse = _admit(
        admission,
        request_id="request-2",
        assertion=_assertion(nonce="nonce-00000002"),
    )

    assert reuse.admitted is False
    assert reuse.reason is DenyReason.APPROVAL_CONSUMED


def test_a_duplicate_request_id_replays_the_prior_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _admission()
    denied = _admit(admission, assertion=_assertion(issuer="https://attacker.invalid"))
    assert denied.admitted is False

    repeat = _admit(admission, assertion=_assertion(issuer="https://attacker.invalid"))

    assert repeat.reason is denied.reason
    assert repeat.replayed is True


def test_a_request_still_in_progress_is_not_admitted_again() -> None:
    admission = _admission()
    first = _admit(admission, request_id="request-1")
    assert first.admitted is True

    second = admission.admit(
        request_id="request-1",
        tool=TOOL,
        assertion=_assertion(nonce="nonce-00000009"),
        action_digest=DIGEST,
        policy_version="1.0",
        approval=_approval(approval_id="approval-9"),
    )

    assert second.admitted is False
    assert second.reason is DenyReason.REQUEST_IN_PROGRESS


def test_a_terminal_result_makes_a_repeat_replay_the_decision() -> None:
    admission = _admission()
    first = _admit(admission, request_id="request-1")
    admission.record_terminal(first)

    repeat = _admit(admission, request_id="request-1")

    assert repeat.admitted is True
    assert repeat.replayed is True


def test_the_component_opens_no_socket_and_starts_no_process(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket
    import subprocess

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the admission decision must not perform I/O")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)

    assert _admit(_admission()).admitted is True


def test_every_denial_carries_exactly_one_reason() -> None:
    admission = _admission(profile=ProtectionProfile())

    decision = _admit(admission)

    assert decision.admitted is False
    assert decision.reason is not None
    assert isinstance(decision.reason, DenyReason)
