"""Typed contracts for external verification and evidence bundles."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegistryClaimStatus(StrEnum):
    """Implementation status declared by the project."""

    IMPLEMENTED = "implemented"
    VERIFIED_IN_CI = "verified-in-ci"
    PLANNED = "planned"
    UNVERIFIED = "unverified"


class VerificationStatus(StrEnum):
    """Outcome produced by an independent verification attempt."""

    VERIFIED = "verified"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    POLICY_DENIED = "policy_denied"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class BackendName(StrEnum):
    """Execution backends exposed by the verification CLI."""

    AUTO = "auto"
    OPENSHELL = "openshell"
    DOCKER = "docker"
    PODMAN = "podman"
    UNSAFE_LOCAL = "unsafe-local"


class NetworkMode(StrEnum):
    """Network authority requested by a verification recipe."""

    DENY = "deny"


class VerificationRecipe(BaseModel):
    """A bounded argv-only verification command."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = "."
    timeout_seconds: int = Field(default=120, ge=1, le=900)
    expected_exit_codes: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=16)
    network: NetworkMode = NetworkMode.DENY
    max_output_bytes: int = Field(default=1_048_576, ge=1_024, le=16_777_216)
    artifacts: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("argv entries must be non-empty and contain no NUL bytes")
        return value

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("cwd must remain relative to the verification root")
        return value or "."

    @field_validator("artifacts")
    @classmethod
    def validate_artifacts(cls, value: list[str]) -> list[str]:
        for item in value:
            path = PurePosixPath(item)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("artifact paths must remain relative to the verification root")
        return value


class ExpectedVerification(BaseModel):
    """Expected high-level outcome for a claim recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: VerificationStatus = VerificationStatus.VERIFIED
    assertions: dict[str, Any] = Field(default_factory=dict)


class VerificationClaim(BaseModel):
    """One claim and the evidence required to verify it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    claim: str = Field(min_length=1)
    status: RegistryClaimStatus
    evidence: list[str] = Field(min_length=1)
    verification: VerificationRecipe | None = None
    expected: ExpectedVerification | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_recipe_for_runnable_claim(self) -> VerificationClaim:
        if self.status in {RegistryClaimStatus.IMPLEMENTED, RegistryClaimStatus.VERIFIED_IN_CI}:
            if self.verification is None:
                raise ValueError("implemented claims require a verification recipe")
            if self.expected is None:
                raise ValueError("implemented claims require an expected result")
        return self


class VerificationContract(BaseModel):
    """Repository-wide safety limits for recipe execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executable_allowlist: list[str] = Field(min_length=1)
    default_backend: BackendName = BackendName.AUTO
    strong_backends: list[BackendName] = Field(
        default_factory=lambda: [BackendName.OPENSHELL, BackendName.PODMAN, BackendName.DOCKER]
    )
    unsafe_local_requires_explicit_opt_in: bool = True
    environment_allowlist: list[str] = Field(default_factory=list)


class EvidenceRegistry(BaseModel):
    """Versioned claim-to-recipe registry."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_url: str | None = Field(default=None, alias="$schema")
    schema_version: Literal["2.0"]
    project: str
    version: str
    maturity: str
    license: str
    repository: str
    verification_contract: VerificationContract
    claims: list[VerificationClaim] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_claim_ids(self) -> EvidenceRegistry:
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim ids must be unique")
        return self

    def claim_by_id(self, claim_id: str) -> VerificationClaim:
        for claim in self.claims:
            if claim.id == claim_id:
                return claim
        raise KeyError(claim_id)


class ReadinessComponent(StrEnum):
    """Separately observable prerequisite of a strong backend."""

    EXECUTABLE = "executable"
    POLICY = "policy"
    VERSION = "version"
    GATEWAY = "gateway"
    RUNTIME = "runtime"


class BackendReadiness(BaseModel):
    """One readiness component and the exact reason it is or is not ready."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    component: ReadinessComponent
    ready: bool
    reason: str = Field(max_length=2048)


class BackendAvailability(BaseModel):
    """Runtime discovery result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: BackendName
    available: bool
    executable: str | None = None
    strong_isolation: bool
    reason: str
    components: list[BackendReadiness] = Field(default_factory=list, max_length=16)


class DoctorReport(BaseModel):
    """Machine-readable environment report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project: str
    project_version: str
    repository_root: str
    registry_path: str
    registry_sha256: str
    python_version: str
    backends: list[BackendAvailability]
    selected_backend: BackendName | None
    notes: list[str] = Field(default_factory=list)


class SourceIdentity(BaseModel):
    """Identity of the source tree being verified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str
    commit_sha: str | None = None
    dirty: bool | None = None


class CommandEvidence(BaseModel):
    """Bounded process output captured from one recipe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: list[str]
    cwd: str
    exit_code: int | None = None
    duration_ms: float = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False


class VerificationResult(BaseModel):
    """Portable result for one claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project: str
    project_version: str
    claim_id: str
    claim: str
    declared_status: RegistryClaimStatus
    status: VerificationStatus
    backend: BackendName
    source: SourceIdentity
    registry_sha256: str
    recipe_sha256: str | None = None
    policy_sha256: str | None = None
    started_at: str
    finished_at: str
    command: CommandEvidence | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    reason: str


class VerificationSummary(BaseModel):
    """Aggregate result emitted by ``xt-aegis verify``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project: str
    project_version: str
    backend: BackendName
    source: SourceIdentity
    registry_sha256: str
    started_at: str
    finished_at: str
    results: list[VerificationResult]
    counts: dict[str, int]
    overall_status: VerificationStatus


class EvidenceBundleFile(BaseModel):
    """File entry included in an evidence bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str
    size_bytes: int = Field(ge=0)


class EvidenceBundleManifest(BaseModel):
    """Integrity manifest stored inside a deterministic archive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project: str
    created_at: str
    files: list[EvidenceBundleFile]
    note: str = "SHA-256 entries provide integrity checking only. They do not establish publisher identity."
