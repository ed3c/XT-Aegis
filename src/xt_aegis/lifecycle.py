"""Named execution transitions, cancellation, and deadlines shared by the runner and its tests."""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class Transition(StrEnum):
    """Every persisted or side-effecting boundary the runtime can be interrupted at.

    The names are a contract: fault injection, cancellation checks, and the documented recovery table all
    address the same points, so a new boundary cannot be added to one of them and forgotten in the others.
    """

    REQUEST_RECEIVED = "request_received"
    POLICY_EVALUATED = "policy_evaluated"
    STEP_PREPARED = "step_prepared"
    APPROVAL_RESOLVED = "approval_resolved"
    SNAPSHOT_CREATED = "snapshot_created"
    PRECONDITION_CHECKED = "precondition_checked"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    POSTCONDITION_CHECKED = "postcondition_checked"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_COMPLETED = "rollback_completed"
    RESULT_SAVED = "result_saved"


class ExecutionCancelled(RuntimeError):
    """Raised at a transition when the caller cancelled the request."""


class DeadlineExceeded(RuntimeError):
    """Raised at a transition when the caller's wall-clock deadline has passed."""


class CancellationToken:
    """Cooperative cancellation with an optional deadline; both are checked only at named transitions.

    Checking at transitions rather than mid-call is deliberate: a request is interrupted at a boundary the
    recovery table documents, never in the middle of a snapshot copy or a database write.
    """

    def __init__(self, *, deadline: float | None = None, clock: Callable[[], float] | None = None) -> None:
        self._cancelled = False
        self._deadline = deadline
        self._clock = clock or time.monotonic

    @classmethod
    def with_timeout(
        cls, seconds: float | None, *, clock: Callable[[], float] | None = None
    ) -> CancellationToken:
        resolved_clock = clock or time.monotonic
        deadline = resolved_clock() + seconds if seconds is not None else None
        return cls(deadline=deadline, clock=resolved_clock)

    @property
    def deadline(self) -> float | None:
        return self._deadline

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Request cancellation; the next transition fails closed."""

        self._cancelled = True

    def remaining_seconds(self) -> float | None:
        if self._deadline is None:
            return None
        return self._deadline - self._clock()

    def raise_if_unavailable(self) -> None:
        """Fail closed at a transition boundary. Cancellation wins over an expired deadline."""

        if self._cancelled:
            raise ExecutionCancelled("the request was cancelled by its caller")
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise DeadlineExceeded("the request deadline expired")
