"""Domain errors raised by XT-Aegis."""

from __future__ import annotations


class XTAegisError(Exception):
    """Base exception for XT-Aegis."""


class SkillCompileError(XTAegisError):
    """Raised when a SKILL contract cannot be parsed or validated."""


class PolicyViolation(XTAegisError):
    """Raised when an action violates a deterministic policy."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class WorkspaceSafetyError(XTAegisError):
    """Raised when a workspace path or transaction is unsafe."""


class ApprovalError(XTAegisError):
    """Raised when an approval transition is invalid."""


class IdempotencyConflictError(XTAegisError):
    """Raised when one idempotency key is reused for another canonical request."""

    def __init__(self, message: str, *, step_number: int = 0) -> None:
        self.step_number = step_number
        super().__init__(message)


class CheckpointSchemaError(XTAegisError):
    """Raised when a persisted checkpoint schema is unsupported."""
