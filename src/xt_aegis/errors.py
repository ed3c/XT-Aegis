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
