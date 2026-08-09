"""Transactional, checkpointed executor for validated skill contracts."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EventRecorder
from xt_aegis.models import (
    ActionRequest,
    CheckResult,
    CommandAction,
    CommandSpec,
    CompiledSkill,
    ExecutionResult,
    ExecutionStatus,
    FileWriteAction,
    RiskLevel,
)
from xt_aegis.policy import PolicyEngine
from xt_aegis.redaction import redact_text
from xt_aegis.errors import PolicyViolation, WorkspaceSafetyError
from xt_aegis.workspace import IsolatedWorkspace, WorkspaceTransaction


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class HarnessRunner:
    """Keep model proposals separate from deterministic execution controls."""

    def __init__(
        self,
        *,
        skill: CompiledSkill,
        workspace: IsolatedWorkspace,
        checkpoint_store: CheckpointStore,
        event_recorder: EventRecorder | None = None,
    ) -> None:
        self.skill = skill
        self.workspace = workspace
        self.store = checkpoint_store
        self.events = event_recorder or EventRecorder(checkpoint_store)
        self.policy = PolicyEngine(skill.contract, workspace)
        self._runner_started = time.monotonic()

    def approve(self, approval_id: str, *, reviewer: str) -> None:
        self.store.decide_approval(approval_id, decision="approved", reviewer=reviewer)

    def deny(self, approval_id: str, *, reviewer: str) -> None:
        self.store.decide_approval(approval_id, decision="denied", reviewer=reviewer)

    def execute(self, request: ActionRequest) -> ExecutionResult:
        trace_id = self.events.new_trace_id()
        self.store.start_run(request.thread_id, self.skill.contract.name)

        cached = self.store.get_cached_result(request.idempotency_key)
        if cached is not None:
            self.events.emit(
                trace_id=trace_id,
                thread_id=request.thread_id,
                event_type="idempotent_replay",
                payload={"action_id": request.action_id, "step_number": cached.step_number},
            )
            return cached

        step_number = self.store.prepare_step(request)
        started_at = _utc_now()
        started_clock = time.perf_counter()
        before_sha = self.workspace.hash_tree()
        self.events.emit(
            trace_id=trace_id,
            thread_id=request.thread_id,
            event_type="action_received",
            payload={
                "action_id": request.action_id,
                "step_number": step_number,
                "provenance": request.provenance.value,
                "kind": request.action.kind,
            },
        )

        budget_reasons = self._budget_reasons(step_number)
        if budget_reasons:
            result = self._terminal_result(
                request=request,
                step_number=step_number,
                status=ExecutionStatus.BLOCKED,
                success=False,
                before_sha=before_sha,
                after_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                policy_reasons=budget_reasons,
            )
            return self._persist_and_emit(trace_id, result, "budget_blocked")

        try:
            self.policy.validate_request(request)
            for condition in (*self.skill.contract.preconditions, *self.skill.contract.postconditions):
                self.policy.validate_condition(condition)
        except PolicyViolation as exc:
            result = self._terminal_result(
                request=request,
                step_number=step_number,
                status=ExecutionStatus.BLOCKED,
                success=False,
                before_sha=before_sha,
                after_sha=self.workspace.hash_tree(),
                started_at=started_at,
                started_clock=started_clock,
                policy_reasons=exc.reasons,
            )
            return self._persist_and_emit(trace_id, result, "policy_blocked")

        if self._requires_approval() and not self.store.approval_is_valid(request.approval_id, request):
            approval_id = self.store.get_or_create_approval(request)
            result = self._terminal_result(
                request=request,
                step_number=step_number,
                status=ExecutionStatus.SUSPENDED,
                success=False,
                before_sha=before_sha,
                after_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                approval_id=approval_id,
                policy_reasons=["human approval is required before this action may execute"],
            )
            return self._persist_and_emit(trace_id, result, "approval_required")

        transaction: WorkspaceTransaction | None = None
        preconditions: list[CheckResult] = []
        postconditions: list[CheckResult] = []
        action_exit_code: int | None = None
        action_stdout = ""
        action_stderr = ""

        try:
            transaction = self.workspace.begin_transaction()
            before_sha = transaction.before_sha256

            for condition in self.skill.contract.preconditions:
                check = self._run_command(condition)
                preconditions.append(check)
                self.events.emit(
                    trace_id=trace_id,
                    thread_id=request.thread_id,
                    event_type="precondition_checked",
                    payload={"description": check.description, "passed": check.passed},
                )
                if not check.passed:
                    rollback_integrity = transaction.rollback()
                    after_sha = self.workspace.hash_tree()
                    result = self._terminal_result(
                        request=request,
                        step_number=step_number,
                        status=ExecutionStatus.ROLLED_BACK,
                        success=False,
                        before_sha=before_sha,
                        after_sha=after_sha,
                        started_at=started_at,
                        started_clock=started_clock,
                        preconditions=preconditions,
                        rolled_back=True,
                        rollback_integrity=rollback_integrity,
                        action_stderr="precondition failed; action was not executed",
                    )
                    return self._persist_and_emit(trace_id, result, "precondition_failed")

            action_exit_code, action_stdout, action_stderr = self._execute_action(request)
            if action_exit_code != 0:
                rollback_integrity = transaction.rollback()
                after_sha = self.workspace.hash_tree()
                result = self._terminal_result(
                    request=request,
                    step_number=step_number,
                    status=ExecutionStatus.ROLLED_BACK,
                    success=False,
                    before_sha=before_sha,
                    after_sha=after_sha,
                    started_at=started_at,
                    started_clock=started_clock,
                    preconditions=preconditions,
                    action_exit_code=action_exit_code,
                    action_stdout=action_stdout,
                    action_stderr=action_stderr,
                    rolled_back=True,
                    rollback_integrity=rollback_integrity,
                )
                return self._persist_and_emit(trace_id, result, "action_failed")

            for condition in self.skill.contract.postconditions:
                check = self._run_command(condition)
                postconditions.append(check)
                self.events.emit(
                    trace_id=trace_id,
                    thread_id=request.thread_id,
                    event_type="postcondition_checked",
                    payload={"description": check.description, "passed": check.passed},
                )
                if not check.passed:
                    rollback_integrity = transaction.rollback()
                    after_sha = self.workspace.hash_tree()
                    result = self._terminal_result(
                        request=request,
                        step_number=step_number,
                        status=ExecutionStatus.ROLLED_BACK,
                        success=False,
                        before_sha=before_sha,
                        after_sha=after_sha,
                        started_at=started_at,
                        started_clock=started_clock,
                        preconditions=preconditions,
                        postconditions=postconditions,
                        action_exit_code=action_exit_code,
                        action_stdout=action_stdout,
                        action_stderr=action_stderr,
                        rolled_back=True,
                        rollback_integrity=rollback_integrity,
                    )
                    return self._persist_and_emit(trace_id, result, "postcondition_failed")

            transaction.commit()
            after_sha = self.workspace.hash_tree()
            result = self._terminal_result(
                request=request,
                step_number=step_number,
                status=ExecutionStatus.SUCCEEDED,
                success=True,
                before_sha=before_sha,
                after_sha=after_sha,
                started_at=started_at,
                started_clock=started_clock,
                preconditions=preconditions,
                postconditions=postconditions,
                action_exit_code=action_exit_code,
                action_stdout=action_stdout,
                action_stderr=action_stderr,
            )
            return self._persist_and_emit(trace_id, result, "action_succeeded")

        except (OSError, subprocess.SubprocessError, WorkspaceSafetyError) as exc:
            rollback_integrity: bool | None = None
            rolled_back = False
            if transaction is not None:
                try:
                    rollback_integrity = transaction.rollback()
                    rolled_back = True
                except WorkspaceSafetyError:
                    rollback_integrity = False
            after_sha = self.workspace.hash_tree()
            status = ExecutionStatus.ROLLED_BACK if rolled_back and rollback_integrity else ExecutionStatus.FAILED
            result = self._terminal_result(
                request=request,
                step_number=step_number,
                status=status,
                success=False,
                before_sha=before_sha,
                after_sha=after_sha,
                started_at=started_at,
                started_clock=started_clock,
                preconditions=preconditions,
                postconditions=postconditions,
                action_exit_code=action_exit_code,
                action_stdout=action_stdout,
                action_stderr=f"{action_stderr}\n{type(exc).__name__}: {exc}".strip(),
                rolled_back=rolled_back,
                rollback_integrity=rollback_integrity,
            )
            return self._persist_and_emit(trace_id, result, "executor_exception")

    def _requires_approval(self) -> bool:
        return self.skill.contract.requires_approval or self.skill.contract.risk_level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }

    def _budget_reasons(self, step_number: int) -> list[str]:
        reasons: list[str] = []
        if step_number > self.skill.contract.max_steps:
            reasons.append(f"step budget exceeded: {step_number} > {self.skill.contract.max_steps}")
        elapsed = time.monotonic() - self._runner_started
        if elapsed > self.skill.contract.max_total_seconds:
            reasons.append(
                f"wall-clock budget exceeded: {elapsed:.3f}s > {self.skill.contract.max_total_seconds:.3f}s"
            )
        return reasons

    def _execute_action(self, request: ActionRequest) -> tuple[int | None, str, str]:
        if isinstance(request.action, FileWriteAction):
            target = self.workspace.resolve_relative(request.action.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor, temporary_name = tempfile.mkstemp(prefix=".xt-aegis-write-", dir=target.parent)
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(request.action.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, target)
            finally:
                temporary_path.unlink(missing_ok=True)
            return 0, f"wrote {len(request.action.content.encode('utf-8'))} bytes", ""

        if isinstance(request.action, CommandAction):
            result = self._run_command(request.action.command)
            return result.exit_code, result.stdout, result.stderr

        raise TypeError(f"unsupported action: {type(request.action).__name__}")

    def _run_command(self, command: CommandSpec) -> CheckResult:
        cwd = self.workspace.resolve_relative(command.cwd)
        home = self.workspace.run_root / "home"
        home.mkdir(parents=True, exist_ok=True)
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command.argv,
                cwd=cwd,
                env=environment,
                shell=False,
                capture_output=True,
                text=True,
                timeout=command.timeout_seconds,
                check=False,
            )
            exit_code: int | None = completed.returncode
            stdout = redact_text(completed.stdout)
            stderr = redact_text(completed.stderr)
            passed = completed.returncode in command.expected_exit_codes
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            stdout = redact_text(exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = redact_text((exc.stderr or "") if isinstance(exc.stderr, str) else "")
            stderr = f"{stderr}\ncommand timed out after {command.timeout_seconds}s".strip()
            passed = False
        duration_ms = (time.perf_counter() - started) * 1000
        return CheckResult(
            description=command.description,
            passed=passed,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
        )

    def _terminal_result(
        self,
        *,
        request: ActionRequest,
        step_number: int,
        status: ExecutionStatus,
        success: bool,
        before_sha: str,
        after_sha: str,
        started_at: str,
        started_clock: float,
        policy_reasons: list[str] | None = None,
        approval_id: str | None = None,
        preconditions: list[CheckResult] | None = None,
        postconditions: list[CheckResult] | None = None,
        action_exit_code: int | None = None,
        action_stdout: str = "",
        action_stderr: str = "",
        rolled_back: bool = False,
        rollback_integrity: bool | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            thread_id=request.thread_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            step_number=step_number,
            status=status,
            success=success,
            policy_reasons=policy_reasons or [],
            approval_id=approval_id,
            preconditions=preconditions or [],
            postconditions=postconditions or [],
            action_exit_code=action_exit_code,
            action_stdout=redact_text(action_stdout),
            action_stderr=redact_text(action_stderr),
            rolled_back=rolled_back,
            rollback_integrity=rollback_integrity,
            workspace_before_sha256=before_sha,
            workspace_after_sha256=after_sha,
            started_at=started_at,
            finished_at=_utc_now(),
            duration_ms=(time.perf_counter() - started_clock) * 1000,
        )

    def _persist_and_emit(
        self,
        trace_id: str,
        result: ExecutionResult,
        event_type: str,
    ) -> ExecutionResult:
        self.store.save_result(result)
        self.events.emit(
            trace_id=trace_id,
            thread_id=result.thread_id,
            event_type=event_type,
            payload={
                "action_id": result.action_id,
                "step_number": result.step_number,
                "status": result.status.value,
                "success": result.success,
                "rolled_back": result.rolled_back,
                "rollback_integrity": result.rollback_integrity,
                "duration_ms": round(result.duration_ms, 3),
            },
        )
        return result
