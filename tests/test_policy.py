from __future__ import annotations

from pathlib import Path

import pytest

from xt_aegis.errors import PolicyViolation
from xt_aegis.models import (
    ActionRequest,
    CommandAction,
    CommandSpec,
    FileWriteAction,
    Provenance,
)


def test_external_content_cannot_execute(runner) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.policy.1",
        action_id="external.write",
        idempotency_key="external-content-0001",
        provenance=Provenance.EXTERNAL_CONTENT,
        action=FileWriteAction(relative_path="sample_project/app.py", content="# injected\n"),
    )
    with pytest.raises(PolicyViolation, match="external or retrieved content"):
        runner.policy.validate_request(request)


def test_path_traversal_is_denied(runner) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.policy.2",
        action_id="escape.write",
        idempotency_key="path-traversal-0001",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(relative_path="../outside.py", content="pass\n"),
    )
    with pytest.raises(PolicyViolation, match="normalized relative path"):
        runner.policy.validate_request(request)


def test_shell_operators_are_denied(runner) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.policy.3",
        action_id="shell.operator",
        idempotency_key="shell-operator-0001",
        provenance=Provenance.AGENT_PROPOSAL,
        action=CommandAction(
            command=CommandSpec(description="unsafe", argv=["python3", "-m", "unittest", "&&", "echo"])
        ),
    )
    with pytest.raises(PolicyViolation, match="control fragment"):
        runner.policy.validate_request(request)


def test_inline_interpreter_code_is_denied(runner) -> None:  # type: ignore[no-untyped-def]
    request = ActionRequest(
        thread_id="thread.policy.4",
        action_id="inline.code",
        idempotency_key="inline-python-0001",
        provenance=Provenance.AGENT_PROPOSAL,
        action=CommandAction(command=CommandSpec(description="inline", argv=["python3", "-c", "print(1)"])),
    )
    with pytest.raises(PolicyViolation, match="inline interpreter code"):
        runner.policy.validate_request(request)


def test_expected_hash_detects_stale_plan(runner) -> None:  # type: ignore[no-untyped-def]
    path: Path = runner.workspace.root / "sample_project" / "app.py"
    request = ActionRequest(
        thread_id="thread.policy.5",
        action_id="stale.write",
        idempotency_key="stale-plan-hash-0001",
        provenance=Provenance.AGENT_PROPOSAL,
        action=FileWriteAction(
            relative_path="sample_project/app.py",
            content="pass\n",
            expected_sha256="0" * 64,
        ),
    )
    assert path.is_file()
    with pytest.raises(PolicyViolation, match="changed since"):
        runner.policy.validate_request(request)
