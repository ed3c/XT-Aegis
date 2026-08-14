"""Transactional, checkpointed executor for validated skill contracts."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import tempfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.errors import IdempotencyConflictError, PolicyViolation, WorkspaceSafetyError
from xt_aegis.events import EventRecorder
from xt_aegis.identity import RequestIdentity
from xt_aegis.models import (
    ActionRequest,
    CheckResult,
    CommandAction,
    CommandSpec,
    CompiledSkill,
    ExecutionReasonCode,
    ExecutionResult,
    ExecutionStatus,
    FileWriteAction,
    RiskLevel,
)
from xt_aegis.policy import PolicyEngine
from xt_aegis.redaction import redact_text
from xt_aegis.telemetry import NullTelemetry, SpanName, Telemetry
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
        telemetry: Telemetry | None = None,
    ) -> None:
        self.skill = skill
        self.workspace = workspace
        self.store = checkpoint_store
        self.events = event_recorder or EventRecorder(checkpoint_store)
        self.telemetry = telemetry or NullTelemetry()
        self.policy = PolicyEngine(skill.contract, workspace)
        self._runner_started = time.monotonic()

    def approve(self, approval_id: str, *, reviewer: str) -> None:
        self.store.decide_approval(approval_id, decision="approved", reviewer=reviewer)

    def deny(self, approval_id: str, *, reviewer: str) -> None:
        self.store.decide_approval(approval_id, decision="denied", reviewer=reviewer)

    def execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float | None = None,
        max_output_bytes: int = 16_384,
    ) -> ExecutionResult:
        """Execute once and return output bounded for the calling controller."""

        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        return self._bound_execution_output(
            self._execute(
                request,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            ),
            max_output_bytes,
        )

    def _execute(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float | None,
        max_output_bytes: int,
    ) -> ExecutionResult:
        with self.telemetry.span(
            SpanName.RUN,
            thread_id=request.thread_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            provenance=request.provenance.value,
            kind=request.action.kind,
            skill=self.skill.contract.name,
            risk_level=self.skill.contract.risk_level.value,
        ) as span:
            result = self._execute_traced(
                request,
                timeout_seconds=timeout_seconds,
                max_output_bytes=max_output_bytes,
            )
            span.set(
                status=result.status.value,
                success=result.success,
                step_number=result.step_number,
                reason_code=result.reason_code.value if result.reason_code is not None else None,
            )
            if result.status == ExecutionStatus.FAILED:
                span.fail()
            return result

    def _execute_traced(
        self,
        request: ActionRequest,
        *,
        timeout_seconds: float | None,
        max_output_bytes: int,
    ) -> ExecutionResult:
        trace_id = self.events.new_trace_id()
        identity = RequestIdentity.from_request(request, skill=self.skill)
        self.store.start_run(request.thread_id, self.skill.contract.name)
        started_at = _utc_now()
        started_clock = time.perf_counter()
        deadline = started_clock + timeout_seconds if timeout_seconds is not None else None
        before_sha = self.workspace.hash_tree()

        self.events.emit(
            trace_id=trace_id,
            thread_id=request.thread_id,
            event_type="action_received",
            payload={
                "action_id": request.action_id,
                "provenance": request.provenance.value,
                "kind": request.action.kind,
                "request_digest_version": identity.version,
                "request_digest": identity.digest,
                "policy_digest": identity.policy_digest,
            },
        )

        try:
            cached = self.store.get_cached_result(request.idempotency_key, identity)
        except IdempotencyConflictError as exc:
            return self._emit_identity_conflict(
                trace_id=trace_id,
                request=request,
                identity=identity,
                step_number=exc.step_number,
                before_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                reason=str(exc),
            )

        try:
            with self.telemetry.span(SpanName.POLICY_EVALUATE, action_id=request.action_id) as policy_span:
                try:
                    self.policy.validate_request(request)
                    for condition in (
                        *self.skill.contract.preconditions,
                        *self.skill.contract.postconditions,
                    ):
                        self.policy.validate_condition(condition)
                except PolicyViolation:
                    policy_span.set(passed=False)
                    raise
                policy_span.set(passed=True)
        except PolicyViolation as exc:
            try:
                step_number = self.store.prepare_step(request, identity)
            except IdempotencyConflictError as conflict:
                return self._emit_identity_conflict(
                    trace_id=trace_id,
                    request=request,
                    identity=identity,
                    step_number=conflict.step_number,
                    before_sha=before_sha,
                    started_at=started_at,
                    started_clock=started_clock,
                    reason=str(conflict),
                )
            result = self._terminal_result(
                request=request,
                identity=identity,
                step_number=step_number,
                status=ExecutionStatus.BLOCKED,
                success=False,
                before_sha=before_sha,
                after_sha=self.workspace.hash_tree(),
                started_at=started_at,
                started_clock=started_clock,
                policy_reasons=exc.reasons,
                reason_code=ExecutionReasonCode.POLICY_DENIED,
            )
            return self._persist_and_emit(
                trace_id, result, "policy_blocked", max_output_bytes=max_output_bytes
            )

        if cached is not None:
            self.events.emit(
                trace_id=trace_id,
                thread_id=request.thread_id,
                event_type="idempotent_replay",
                payload={
                    "action_id": request.action_id,
                    "step_number": cached.step_number,
                    "request_digest_version": identity.version,
                    "request_digest": identity.digest,
                },
            )
            return cached

        try:
            step_number = self.store.prepare_step(request, identity)
        except IdempotencyConflictError as exc:
            return self._emit_identity_conflict(
                trace_id=trace_id,
                request=request,
                identity=identity,
                step_number=exc.step_number,
                before_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                reason=str(exc),
            )

        budget_reasons = self._budget_reasons(step_number)
        if budget_reasons:
            result = self._terminal_result(
                request=request,
                identity=identity,
                step_number=step_number,
                status=ExecutionStatus.BLOCKED,
                success=False,
                before_sha=before_sha,
                after_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                policy_reasons=budget_reasons,
                reason_code=ExecutionReasonCode.BUDGET_EXHAUSTED,
            )
            return self._persist_and_emit(
                trace_id, result, "budget_blocked", max_output_bytes=max_output_bytes
            )

        approval_claimed = True
        if self._requires_approval():
            with self.telemetry.span(
                SpanName.APPROVAL_WAIT,
                action_id=request.action_id,
                approval_id=request.approval_id,
                risk_level=self.skill.contract.risk_level.value,
            ) as approval_span:
                approval_claimed = self.store.claim_approval(request.approval_id, request, identity)
                approval_span.set(outcome="claimed" if approval_claimed else "not_claimed")
        if not approval_claimed:
            approval_state = self.store.approval_state(request.approval_id, request, identity)
            if approval_state == "denied":
                result = self._terminal_result(
                    request=request,
                    identity=identity,
                    step_number=step_number,
                    status=ExecutionStatus.BLOCKED,
                    success=False,
                    before_sha=before_sha,
                    after_sha=before_sha,
                    started_at=started_at,
                    started_clock=started_clock,
                    approval_id=request.approval_id,
                    policy_reasons=["human approval was denied for this exact request"],
                    reason_code=ExecutionReasonCode.APPROVAL_DENIED,
                )
                return self._persist_and_emit(
                    trace_id, result, "approval_denied", max_output_bytes=max_output_bytes
                )

            approval_id = self.store.get_or_create_approval(request, identity)
            result = self._terminal_result(
                request=request,
                identity=identity,
                step_number=step_number,
                status=ExecutionStatus.SUSPENDED,
                success=False,
                before_sha=before_sha,
                after_sha=before_sha,
                started_at=started_at,
                started_clock=started_clock,
                approval_id=approval_id,
                policy_reasons=["human approval is required before this exact request may execute"],
                reason_code=ExecutionReasonCode.APPROVAL_REQUIRED,
            )
            return self._persist_and_emit(
                trace_id, result, "approval_required", max_output_bytes=max_output_bytes
            )

        transaction: WorkspaceTransaction | None = None
        preconditions: list[CheckResult] = []
        postconditions: list[CheckResult] = []
        action_exit_code: int | None = None
        action_expected_exit_codes: list[int] = []
        action_stdout = ""
        action_stderr = ""
        rollback_integrity: bool | None = None
        remaining_output_bytes = max_output_bytes
        total_output_original_bytes = 0

        try:
            transaction = self.workspace.begin_transaction()
            before_sha = transaction.before_sha256

            for check_index, condition in enumerate(self.skill.contract.preconditions):
                check = self._checked_condition(
                    condition,
                    check_kind="precondition",
                    check_index=check_index,
                    deadline=deadline,
                    max_output_bytes=remaining_output_bytes,
                )
                preconditions.append(check)
                total_output_original_bytes += check.output_original_bytes
                remaining_output_bytes -= len((check.stdout + check.stderr).encode())
                self.events.emit(
                    trace_id=trace_id,
                    thread_id=request.thread_id,
                    event_type="precondition_checked",
                    payload={
                        "description": check.description,
                        "passed": check.passed,
                        "actual_exit_code": check.exit_code,
                        "expected_exit_codes": sorted(condition.expected_exit_codes),
                    },
                )
                if not check.passed:
                    rollback_integrity = self._rollback(transaction)
                    after_sha = self.workspace.hash_tree()
                    result = self._terminal_result(
                        request=request,
                        identity=identity,
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
                        action_stderr=(
                            "" if check.output_truncated else "precondition failed; action was not executed"
                        ),
                        reason_code=(
                            ExecutionReasonCode.OUTPUT_BUDGET_EXHAUSTED if check.output_truncated else None
                        ),
                        policy_reasons=(
                            [f"command output budget exceeded: > {max_output_bytes} bytes"]
                            if check.output_truncated
                            else None
                        ),
                        output_truncated=check.output_truncated,
                        output_original_bytes=total_output_original_bytes,
                    )
                    return self._persist_and_emit(
                        trace_id, result, "precondition_failed", max_output_bytes=max_output_bytes
                    )

            with self.telemetry.span(
                SpanName.ACTION_EXECUTE, action_id=request.action_id, kind=request.action.kind
            ) as action_span:
                action_result = self._execute_action(
                    request,
                    deadline=deadline,
                    max_output_bytes=remaining_output_bytes,
                )
                action_span.set(passed=action_result.passed, exit_code=action_result.exit_code)
                if not action_result.passed:
                    action_span.fail()
            action_exit_code = action_result.exit_code
            action_expected_exit_codes = self._expected_exit_codes(request)
            action_stdout = action_result.stdout
            action_stderr = action_result.stderr
            total_output_original_bytes += action_result.output_original_bytes
            remaining_output_bytes -= len((action_stdout + action_stderr).encode())
            if not action_result.passed:
                rollback_integrity = self._rollback(transaction)
                after_sha = self.workspace.hash_tree()
                result = self._terminal_result(
                    request=request,
                    identity=identity,
                    step_number=step_number,
                    status=ExecutionStatus.ROLLED_BACK,
                    success=False,
                    before_sha=before_sha,
                    after_sha=after_sha,
                    started_at=started_at,
                    started_clock=started_clock,
                    preconditions=preconditions,
                    action_exit_code=action_exit_code,
                    action_expected_exit_codes=action_expected_exit_codes,
                    action_stdout=action_stdout,
                    action_stderr=action_stderr,
                    rolled_back=True,
                    rollback_integrity=rollback_integrity,
                    reason_code=(
                        ExecutionReasonCode.OUTPUT_BUDGET_EXHAUSTED
                        if action_result.output_truncated
                        else None
                    ),
                    policy_reasons=(
                        [f"command output budget exceeded: > {max_output_bytes} bytes"]
                        if action_result.output_truncated
                        else None
                    ),
                    output_truncated=action_result.output_truncated,
                    output_original_bytes=total_output_original_bytes,
                )
                return self._persist_and_emit(
                    trace_id, result, "action_failed", max_output_bytes=max_output_bytes
                )

            for check_index, condition in enumerate(self.skill.contract.postconditions):
                check = self._checked_condition(
                    condition,
                    check_kind="postcondition",
                    check_index=check_index,
                    deadline=deadline,
                    max_output_bytes=remaining_output_bytes,
                )
                postconditions.append(check)
                total_output_original_bytes += check.output_original_bytes
                remaining_output_bytes -= len((check.stdout + check.stderr).encode())
                self.events.emit(
                    trace_id=trace_id,
                    thread_id=request.thread_id,
                    event_type="postcondition_checked",
                    payload={
                        "description": check.description,
                        "passed": check.passed,
                        "actual_exit_code": check.exit_code,
                        "expected_exit_codes": sorted(condition.expected_exit_codes),
                    },
                )
                if not check.passed:
                    rollback_integrity = self._rollback(transaction)
                    after_sha = self.workspace.hash_tree()
                    result = self._terminal_result(
                        request=request,
                        identity=identity,
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
                        action_expected_exit_codes=action_expected_exit_codes,
                        action_stdout=action_stdout,
                        action_stderr=action_stderr,
                        rolled_back=True,
                        rollback_integrity=rollback_integrity,
                        reason_code=(
                            ExecutionReasonCode.OUTPUT_BUDGET_EXHAUSTED if check.output_truncated else None
                        ),
                        policy_reasons=(
                            [f"command output budget exceeded: > {max_output_bytes} bytes"]
                            if check.output_truncated
                            else None
                        ),
                        output_truncated=check.output_truncated,
                        output_original_bytes=total_output_original_bytes,
                    )
                    return self._persist_and_emit(
                        trace_id, result, "postcondition_failed", max_output_bytes=max_output_bytes
                    )

            transaction.commit()
            after_sha = self.workspace.hash_tree()
            result = self._terminal_result(
                request=request,
                identity=identity,
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
                action_expected_exit_codes=action_expected_exit_codes,
                action_stdout=action_stdout,
                action_stderr=action_stderr,
                output_original_bytes=total_output_original_bytes,
            )
            return self._persist_and_emit(
                trace_id, result, "action_succeeded", max_output_bytes=max_output_bytes
            )

        except (OSError, subprocess.SubprocessError, WorkspaceSafetyError) as exc:
            rollback_integrity = None
            rolled_back = False
            if transaction is not None:
                try:
                    rollback_integrity = self._rollback(transaction)
                    rolled_back = True
                except WorkspaceSafetyError:
                    rollback_integrity = False
            after_sha = self.workspace.hash_tree()
            status = (
                ExecutionStatus.ROLLED_BACK if rolled_back and rollback_integrity else ExecutionStatus.FAILED
            )
            result = self._terminal_result(
                request=request,
                identity=identity,
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
                action_expected_exit_codes=action_expected_exit_codes,
                action_stdout=action_stdout,
                action_stderr=f"{action_stderr}\n{type(exc).__name__}: {exc}".strip(),
                rolled_back=rolled_back,
                rollback_integrity=rollback_integrity,
            )
            return self._persist_and_emit(
                trace_id, result, "executor_exception", max_output_bytes=max_output_bytes
            )

    def _checked_condition(
        self,
        condition: CommandSpec,
        *,
        check_kind: str,
        check_index: int,
        deadline: float | None,
        max_output_bytes: int,
    ) -> CheckResult:
        """Run one declared condition inside its own span without changing the verdict."""

        with self.telemetry.span(
            SpanName.ASSERTION_CHECK,
            check_kind=check_kind,
            check_index=check_index,
            description=condition.description,
        ) as span:
            check = self._run_command(condition, deadline=deadline, max_output_bytes=max_output_bytes)
            span.set(passed=check.passed, exit_code=check.exit_code)
            if not check.passed:
                span.fail()
            return check

    def _rollback(self, transaction: WorkspaceTransaction) -> bool:
        """Every rollback goes through one exit so the span and its verdict cannot be forgotten."""

        with self.telemetry.span(SpanName.WORKSPACE_ROLLBACK) as span:
            integrity = transaction.rollback()
            span.set(rollback_integrity=integrity)
            if not integrity:
                span.fail()
            return integrity

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

    @staticmethod
    def _expected_exit_codes(request: ActionRequest) -> list[int]:
        if isinstance(request.action, CommandAction):
            return sorted(request.action.command.expected_exit_codes)
        return [0]

    def _execute_action(
        self,
        request: ActionRequest,
        *,
        deadline: float | None,
        max_output_bytes: int,
    ) -> CheckResult:
        if isinstance(request.action, FileWriteAction):
            started = time.perf_counter()
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
            message = f"wrote {len(request.action.content.encode('utf-8'))} bytes"
            stdout, _ = self._redact_and_bound_streams(
                message.encode(),
                b"",
                max_output_bytes,
            )
            return CheckResult(
                description=f"write {request.action.relative_path}",
                passed=True,
                exit_code=0,
                duration_ms=(time.perf_counter() - started) * 1000,
                stdout=stdout,
                output_truncated=len(message.encode()) > max_output_bytes,
                output_original_bytes=len(message.encode()),
            )

        if isinstance(request.action, CommandAction):
            return self._run_command(
                request.action.command,
                deadline=deadline,
                max_output_bytes=max_output_bytes,
            )

        raise TypeError(f"unsupported action: {type(request.action).__name__}")

    def _run_command(
        self,
        command: CommandSpec,
        *,
        deadline: float | None,
        max_output_bytes: int,
    ) -> CheckResult:
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
        timeout_seconds = command.timeout_seconds
        if deadline is not None:
            timeout_seconds = max(0.001, min(timeout_seconds, deadline - started))
        process = subprocess.Popen(
            command.argv,
            cwd=cwd,
            env=environment,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout_bytes, stderr_bytes, output_exceeded, timed_out = self._collect_process_output(
            process,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        exit_code = None if timed_out or output_exceeded else process.returncode
        stderr_suffix = f"\ncommand timed out after {timeout_seconds}s" if timed_out else ""
        stdout, stderr = self._redact_and_bound_streams(
            stdout_bytes,
            stderr_bytes + stderr_suffix.encode(),
            max_output_bytes,
        )
        passed = not timed_out and not output_exceeded and process.returncode in command.expected_exit_codes
        duration_ms = (time.perf_counter() - started) * 1000
        return CheckResult(
            description=command.description,
            passed=passed,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            output_truncated=output_exceeded,
            output_original_bytes=(
                max_output_bytes + 1 if output_exceeded else len(stdout_bytes) + len(stderr_bytes)
            ),
        )

    def _terminal_result(
        self,
        *,
        request: ActionRequest,
        identity: RequestIdentity,
        step_number: int,
        status: ExecutionStatus,
        success: bool,
        before_sha: str,
        after_sha: str,
        started_at: str,
        started_clock: float,
        policy_reasons: list[str] | None = None,
        reason_code: ExecutionReasonCode | None = None,
        approval_id: str | None = None,
        preconditions: list[CheckResult] | None = None,
        postconditions: list[CheckResult] | None = None,
        action_exit_code: int | None = None,
        action_expected_exit_codes: list[int] | None = None,
        action_stdout: str = "",
        action_stderr: str = "",
        rolled_back: bool = False,
        rollback_integrity: bool | None = None,
        output_truncated: bool = False,
        output_original_bytes: int = 0,
    ) -> ExecutionResult:
        return ExecutionResult(
            thread_id=request.thread_id,
            action_id=request.action_id,
            idempotency_key=request.idempotency_key,
            step_number=step_number,
            status=status,
            success=success,
            policy_reasons=policy_reasons or [],
            reason_code=reason_code,
            approval_id=approval_id,
            preconditions=preconditions or [],
            postconditions=postconditions or [],
            action_exit_code=action_exit_code,
            action_expected_exit_codes=action_expected_exit_codes or [],
            action_stdout=redact_text(action_stdout),
            action_stderr=redact_text(action_stderr),
            output_truncated=output_truncated,
            output_original_bytes=output_original_bytes,
            rolled_back=rolled_back,
            rollback_integrity=rollback_integrity,
            workspace_before_sha256=before_sha,
            workspace_after_sha256=after_sha,
            request_digest_version=identity.version,
            request_digest=identity.digest,
            policy_digest=identity.policy_digest,
            started_at=started_at,
            finished_at=_utc_now(),
            duration_ms=(time.perf_counter() - started_clock) * 1000,
        )

    @staticmethod
    def _collect_process_output(
        process: subprocess.Popen[bytes],
        *,
        timeout_seconds: float,
        max_output_bytes: int,
    ) -> tuple[bytes, bytes, bool, bool]:
        selector = selectors.DefaultSelector()
        streams = {"stdout": process.stdout, "stderr": process.stderr}
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        started = time.monotonic()
        output_exceeded = False
        timed_out = False
        try:
            for name, stream in streams.items():
                if stream is None:
                    continue
                os.set_blocking(stream.fileno(), False)
                selector.register(stream.fileno(), selectors.EVENT_READ, name)
            while selector.get_map() or process.poll() is None:
                remaining_time = timeout_seconds - (time.monotonic() - started)
                if remaining_time <= 0:
                    timed_out = True
                    break
                if not selector.get_map():
                    try:
                        process.wait(timeout=remaining_time)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                    break
                events = selector.select(remaining_time)
                if not events:
                    if process.poll() is None:
                        timed_out = True
                        break
                    continue
                for key, _ in events:
                    name = key.data
                    file_descriptor = key.fd
                    retained = sum(len(buffer) for buffer in buffers.values())
                    chunk = os.read(
                        file_descriptor,
                        min(65_536, max_output_bytes - retained + 1),
                    )
                    if not chunk:
                        selector.unregister(file_descriptor)
                        continue
                    allowance = max_output_bytes - retained
                    buffers[name].extend(chunk[:allowance])
                    if len(chunk) > allowance:
                        output_exceeded = True
                        break
                if output_exceeded:
                    break
        finally:
            if timed_out or output_exceeded:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            selector.close()
            for stream in streams.values():
                if stream is not None:
                    stream.close()
        return bytes(buffers["stdout"]), bytes(buffers["stderr"]), output_exceeded, timed_out

    @staticmethod
    def _redact_and_bound_streams(
        stdout: bytes,
        stderr: bytes,
        limit: int,
    ) -> tuple[str, str]:
        safe_stdout = redact_text(stdout.decode(errors="ignore")).encode()
        safe_stderr = redact_text(stderr.decode(errors="ignore")).encode()
        retained_stdout = safe_stdout[:limit].decode(errors="ignore")
        retained_stdout_bytes = len(retained_stdout.encode())
        retained_stderr = safe_stderr[: limit - retained_stdout_bytes].decode(errors="ignore")
        return retained_stdout, retained_stderr

    @staticmethod
    def _bound_execution_output(result: ExecutionResult, limit: int) -> ExecutionResult:
        remaining = limit
        retained_bytes = 0

        def bound_check(check: CheckResult) -> CheckResult:
            nonlocal remaining, retained_bytes
            stdout, stderr = HarnessRunner._bound_text_streams(
                check.stdout,
                check.stderr,
                remaining,
            )
            current_bytes = len((check.stdout + check.stderr).encode())
            bounded_bytes = len((stdout + stderr).encode())
            remaining -= bounded_bytes
            retained_bytes += bounded_bytes
            original_bytes = max(check.output_original_bytes, current_bytes)
            return check.model_copy(
                update={
                    "stdout": stdout,
                    "stderr": stderr,
                    "output_truncated": check.output_truncated or original_bytes > bounded_bytes,
                    "output_original_bytes": original_bytes,
                }
            )

        preconditions = [bound_check(check) for check in result.preconditions]
        action_stdout, action_stderr = HarnessRunner._bound_text_streams(
            result.action_stdout,
            result.action_stderr,
            remaining,
        )
        action_retained_bytes = len((action_stdout + action_stderr).encode())
        retained_bytes += action_retained_bytes
        remaining -= action_retained_bytes
        postconditions = [bound_check(check) for check in result.postconditions]

        current_bytes = (
            sum(len((check.stdout + check.stderr).encode()) for check in result.preconditions)
            + len((result.action_stdout + result.action_stderr).encode())
            + sum(len((check.stdout + check.stderr).encode()) for check in result.postconditions)
        )
        original_bytes = max(result.output_original_bytes, current_bytes)
        update: dict[str, object] = {
            "preconditions": preconditions,
            "postconditions": postconditions,
            "action_stdout": action_stdout,
            "action_stderr": action_stderr,
            "output_truncated": result.output_truncated or original_bytes > retained_bytes,
            "output_original_bytes": original_bytes,
        }
        recorded_budget = result.output_budget_bytes
        is_stricter_replay = recorded_budget is not None and limit < recorded_budget
        legacy_evidence_exceeds_limit = recorded_budget is None and current_bytes > limit
        if (
            result.cached_replay
            and result.success
            and original_bytes > limit
            and (is_stricter_replay or legacy_evidence_exceeds_limit)
        ):
            update.update(
                {
                    "status": ExecutionStatus.BLOCKED,
                    "success": False,
                    "reason_code": ExecutionReasonCode.OUTPUT_BUDGET_EXHAUSTED,
                    "policy_reasons": [
                        *result.policy_reasons,
                        f"cached execution output exceeds current budget: {original_bytes} > {limit} bytes",
                    ],
                }
            )
        return result.model_copy(update=update)

    @staticmethod
    def _bound_text_streams(stdout: str, stderr: str, limit: int) -> tuple[str, str]:
        stdout_bytes = stdout.encode()
        stderr_bytes = stderr.encode()
        retained_stdout = stdout_bytes[:limit].decode(errors="ignore")
        retained_stdout_bytes = len(retained_stdout.encode())
        retained_stderr = stderr_bytes[: limit - retained_stdout_bytes].decode(errors="ignore")
        return retained_stdout, retained_stderr

    def _emit_identity_conflict(
        self,
        *,
        trace_id: str,
        request: ActionRequest,
        identity: RequestIdentity,
        step_number: int,
        before_sha: str,
        started_at: str,
        started_clock: float,
        reason: str,
    ) -> ExecutionResult:
        result = self._terminal_result(
            request=request,
            identity=identity,
            step_number=step_number,
            status=ExecutionStatus.BLOCKED,
            success=False,
            before_sha=before_sha,
            after_sha=self.workspace.hash_tree(),
            started_at=started_at,
            started_clock=started_clock,
            policy_reasons=[reason],
            reason_code=ExecutionReasonCode.IDENTITY_CONFLICT,
        )
        self.events.emit(
            trace_id=trace_id,
            thread_id=request.thread_id,
            event_type="idempotency_conflict",
            payload={
                "action_id": request.action_id,
                "step_number": step_number,
                "request_digest_version": identity.version,
                "request_digest": identity.digest,
                "reason": reason,
            },
        )
        return result

    def _persist_and_emit(
        self,
        trace_id: str,
        result: ExecutionResult,
        event_type: str,
        *,
        max_output_bytes: int,
    ) -> ExecutionResult:
        result = self._bound_execution_output(result, max_output_bytes)
        result = result.model_copy(update={"output_budget_bytes": max_output_bytes})
        with self.telemetry.span(
            SpanName.CHECKPOINT_PERSIST,
            event_type=event_type,
            step_number=result.step_number,
            status=result.status.value,
            success=result.success,
        ):
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
                "actual_exit_code": result.action_exit_code,
                "expected_exit_codes": result.action_expected_exit_codes,
                "request_digest_version": result.request_digest_version,
                "request_digest": result.request_digest,
                "duration_ms": round(result.duration_ms, 3),
            },
        )
        return result
