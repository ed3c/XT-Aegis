"""Typed contracts shared by the compiler, policy engine, and harness."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Provenance(StrEnum):
    """Where an executable proposal originated."""

    OPERATOR = "operator"
    AGENT_PROPOSAL = "agent_proposal"
    EXTERNAL_CONTENT = "external_content"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"
    SUSPENDED = "suspended"
    FAILED = "failed"


class ExecutionReasonCode(StrEnum):
    """Machine-readable reason for a terminal executor decision."""

    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_REQUIRED = "approval_required"
    BUDGET_EXHAUSTED = "budget_exhausted"
    IDENTITY_CONFLICT = "identity_conflict"
    OUTPUT_BUDGET_EXHAUSTED = "output_budget_exhausted"


class NetworkPolicy(StrEnum):
    DENY = "deny"
    ALLOWLIST = "allowlist"


class CommandSpec(BaseModel):
    """A command represented as argv; shell strings are intentionally unsupported."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1, max_length=240)
    argv: list[str] = Field(min_length=1, max_length=32)
    cwd: str = "."
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=300.0)
    expected_exit_codes: set[int] = Field(default_factory=lambda: {0}, min_length=1)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("argv entries must be non-empty and cannot contain NUL bytes")
        return value

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        if not value or "\x00" in value:
            raise ValueError("cwd must be a non-empty relative path")
        return value

    @field_validator("expected_exit_codes", mode="before")
    @classmethod
    def validate_expected_exit_codes(cls, value: object) -> object:
        if not isinstance(value, (set, frozenset, list, tuple)) or not value:
            raise ValueError("expected_exit_codes must contain at least one integer exit code")
        for exit_code in value:
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise ValueError("expected_exit_codes entries must be integers")
            if not 0 <= exit_code <= 255:
                raise ValueError("expected_exit_codes entries must be between 0 and 255")
        return value


class FileWriteAction(BaseModel):
    """Atomic write through a deterministic, path-confined tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["write_file"] = "write_file"
    relative_path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=262_144)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class CommandAction(BaseModel):
    """Execute a policy-checked argv command with shell=False."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["command"] = "command"
    command: CommandSpec


Action = Annotated[FileWriteAction | CommandAction, Field(discriminator="kind")]


class SkillContract(BaseModel):
    """Machine-enforced portion of a SKILL.md document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    description: str = Field(min_length=10, max_length=500)
    allowed_executables: set[str] = Field(min_length=1)
    allowed_write_paths: list[str] = Field(default_factory=list)
    denied_argument_fragments: list[str] = Field(
        default_factory=lambda: [";", "&&", "||", "|", "`", "$(", "\n", "\r", ">", "<"]
    )
    network_policy: NetworkPolicy = NetworkPolicy.DENY
    allowed_network_destinations: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    max_steps: int = Field(default=8, ge=1, le=100)
    max_total_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    max_write_bytes: int = Field(default=131_072, ge=1, le=10_485_760)
    preconditions: list[CommandSpec] = Field(default_factory=list, max_length=16)
    postconditions: list[CommandSpec] = Field(default_factory=list, max_length=16)

    @field_validator("allowed_executables")
    @classmethod
    def validate_executables(cls, value: set[str]) -> set[str]:
        for executable in value:
            if not executable or "/" in executable or "\\" in executable:
                raise ValueError("allowed executables must be bare command names")
        return value

    @model_validator(mode="after")
    def validate_network_allowlist(self) -> SkillContract:
        if self.network_policy == NetworkPolicy.ALLOWLIST and not self.allowed_network_destinations:
            raise ValueError("network allowlist policy requires at least one destination")
        if self.network_policy == NetworkPolicy.DENY and self.allowed_network_destinations:
            raise ValueError("network destinations must be empty when network policy is deny")
        return self


class CompiledSkill(BaseModel):
    """Validated skill plus non-executable documentation body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: SkillContract
    markdown_body: str
    source_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ActionRequest(BaseModel):
    """Structured action proposal submitted to the deterministic harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{3,128}$")
    action_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{3,128}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,160}$")
    actor_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:@/-]{1,160}$")
    provenance: Provenance
    action: Action
    approval_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str
    passed: bool
    exit_code: int | None = None
    duration_ms: float = 0.0
    stdout: str = ""
    stderr: str = ""
    output_truncated: bool = False
    output_original_bytes: int = Field(default=0, ge=0)


class ExecutionResult(BaseModel):
    """Serializable result persisted for replay and evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    action_id: str
    idempotency_key: str
    step_number: int
    status: ExecutionStatus
    success: bool
    reason_code: ExecutionReasonCode | None = None
    policy_reasons: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    preconditions: list[CheckResult] = Field(default_factory=list)
    postconditions: list[CheckResult] = Field(default_factory=list)
    action_exit_code: int | None = None
    action_expected_exit_codes: list[int] = Field(default_factory=list)
    action_stdout: str = ""
    action_stderr: str = ""
    output_truncated: bool = False
    output_original_bytes: int = Field(default=0, ge=0)
    output_budget_bytes: int | None = Field(default=None, ge=1)
    rolled_back: bool = False
    rollback_integrity: bool | None = None
    workspace_before_sha256: str
    workspace_after_sha256: str
    cached_replay: bool = False
    request_digest_version: str | None = None
    request_digest: str | None = None
    policy_digest: str | None = None
    started_at: str
    finished_at: str
    duration_ms: float = 0.0


class TrajectoryScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_score: float = Field(ge=0.0, le=1.0)
    safety_score: float = Field(ge=0.0, le=1.0)
    efficiency_score: float = Field(ge=0.0, le=1.0)
    blocked_injection_attempts: int = Field(ge=0)
    rollback_attempts: int = Field(ge=0)
    successful_attempts: int = Field(ge=0)
    notes: list[str] = Field(default_factory=list)
