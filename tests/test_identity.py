from __future__ import annotations

from xt_aegis.identity import RequestIdentity
from xt_aegis.models import (
    ActionRequest,
    CommandAction,
    CommandSpec,
    FileWriteAction,
    Provenance,
)


def test_canonical_identity_is_stable_for_unordered_sets(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    first = ActionRequest(
        thread_id="thread.identity.001",
        action_id="action.identity.001",
        idempotency_key="identity-key-0001",
        provenance=Provenance.OPERATOR,
        action=CommandAction(
            command=CommandSpec(
                description="accepted statuses",
                argv=["python3", "script.py"],
                expected_exit_codes={0, 7, 9},
            )
        ),
    )
    second = ActionRequest.model_validate(
        {
            **first.model_dump(mode="python"),
            "action": {
                "kind": "command",
                "command": {
                    "description": "accepted statuses",
                    "argv": ["python3", "script.py"],
                    "cwd": ".",
                    "timeout_seconds": 10.0,
                    "expected_exit_codes": [9, 0, 7],
                },
            },
        }
    )
    assert RequestIdentity.from_request(first, skill=compiled_skill) == RequestIdentity.from_request(
        second, skill=compiled_skill
    )


def test_approval_id_is_not_part_of_request_identity(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.identity.002",
        action_id="action.identity.002",
        idempotency_key="identity-key-0002",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="sample_project/app.py", content="pass\n"),
    )
    resumed = request.model_copy(update={"approval_id": "a" * 24})
    assert RequestIdentity.from_request(request, skill=compiled_skill) == RequestIdentity.from_request(
        resumed, skill=compiled_skill
    )


def test_payload_and_policy_changes_change_request_identity(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.identity.003",
        action_id="action.identity.003",
        idempotency_key="identity-key-0003",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="sample_project/app.py", content="A\n"),
    )
    changed_payload = request.model_copy(
        update={"action": FileWriteAction(relative_path="sample_project/app.py", content="B\n")}
    )
    changed_policy = compiled_skill.model_copy(
        update={
            "contract": compiled_skill.contract.model_copy(update={"max_write_bytes": 64}),
        }
    )
    base = RequestIdentity.from_request(request, skill=compiled_skill)
    assert RequestIdentity.from_request(changed_payload, skill=compiled_skill).digest != base.digest
    assert RequestIdentity.from_request(request, skill=changed_policy).digest != base.digest


def test_request_identity_matches_versioned_test_vector(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.vector.001",
        action_id="action.vector.001",
        idempotency_key="vector-key-0001",
        actor_id="user:alice",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="sample_project/app.py", content="pass\n"),
    )
    identity = RequestIdentity.from_request(request, skill=compiled_skill)
    assert identity.version == "1.0"
    assert identity.policy_digest == "5285d55cb8e910c0f422d83411b47cfc33dc2052c631340119036cf1be7252df"
    assert identity.digest == "0fd9e42e71c7635d0c05936112677d3acb9735a2044f1a6903f21df27bd26a3c"


def test_identity_binds_path_provenance_actor_and_command_arguments(compiled_skill) -> None:  # type: ignore[no-untyped-def]
    file_request = ActionRequest(
        thread_id="thread.identity.004",
        action_id="action.identity.004",
        idempotency_key="identity-key-0004",
        actor_id="user:alice",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="sample_project/app.py", content="pass\n"),
    )
    base = RequestIdentity.from_request(file_request, skill=compiled_skill).digest
    variants = [
        file_request.model_copy(
            update={
                "action": FileWriteAction(relative_path="sample_project/other.py", content="pass\n")
            }
        ),
        file_request.model_copy(update={"provenance": Provenance.OPERATOR}),
        file_request.model_copy(update={"actor_id": "user:bob"}),
    ]
    assert all(RequestIdentity.from_request(item, skill=compiled_skill).digest != base for item in variants)

    command_request = ActionRequest(
        thread_id="thread.identity.005",
        action_id="action.identity.005",
        idempotency_key="identity-key-0005",
        provenance=Provenance.OPERATOR,
        action=CommandAction(
            command=CommandSpec(
                description="run reviewed test module",
                argv=["python3", "-m", "unittest", "sample_project.test_app"],
            )
        ),
    )
    changed_argument = command_request.model_copy(
        update={
            "action": CommandAction(
                command=command_request.action.command.model_copy(
                    update={"argv": ["python3", "-m", "unittest", "sample_project.other_test"]}
                )
            )
        }
    )
    assert RequestIdentity.from_request(
        changed_argument, skill=compiled_skill
    ).digest != RequestIdentity.from_request(command_request, skill=compiled_skill).digest
