"""The storage contract the runner depends on.

This protocol is descriptive, not aspirational: it records exactly the operations `HarnessRunner` and the
controller already call on the SQLite store. Writing it down is what makes a second backend checkable —
without it, "PostgreSQL support" would mean whatever the second implementation happened to do.
"""

from __future__ import annotations

from typing import Any, Protocol

from xt_aegis.identity import RequestIdentity
from xt_aegis.models import ActionRequest, ExecutionResult


class CheckpointBackend(Protocol):
    """Durable run, step, approval, and event state bound to canonical request identities."""

    def start_run(self, thread_id: str, skill_name: str) -> None:
        """Record that a thread exists; repeated calls are harmless."""

    def set_run_status(self, thread_id: str, status: str) -> None:
        """Update the run's last known status."""

    def get_cached_result(self, idempotency_key: str, identity: RequestIdentity) -> ExecutionResult | None:
        """Return the terminal result for this exact request, or ``None`` when there is not one yet.

        Raises when the key is bound to a different canonical request or policy.
        """

    def prepare_step(self, request: ActionRequest, identity: RequestIdentity) -> int:
        """Reserve or reuse one step number for this exact request."""

    def save_result(self, result: ExecutionResult) -> None:
        """Persist a terminal result whose identity matches the reserved step."""

    def get_or_create_approval(
        self, request: ActionRequest, identity: RequestIdentity, *, ttl_seconds: int = 900
    ) -> str:
        """Return the pending approval for this request, creating or replacing it as needed."""

    def approval_state(
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> str:
        """One of missing, mismatch, expired, consumed, pending, approved, or denied."""

    def approval_is_valid(
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> bool:
        """Whether this approval is currently approved for this exact request."""

    def claim_approval(
        self, approval_id: str | None, request: ActionRequest, identity: RequestIdentity
    ) -> bool:
        """Consume an approved approval exactly once."""

    def decide_approval(self, approval_id: str, *, decision: str, reviewer: str) -> None:
        """Record a human decision on a pending, unexpired approval."""

    def append_event(
        self, *, trace_id: str, thread_id: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        """Append one trajectory event."""

    def list_events(self, thread_id: str) -> list[dict[str, Any]]:
        """Return this thread's events in order."""

    def get_resume_position(self, thread_id: str) -> int:
        """The next step number after every terminal step."""
