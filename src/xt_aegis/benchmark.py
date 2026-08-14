"""Profile-bound deterministic runtime benchmarks that publish raw trials, including failures."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EventRecorder
from xt_aegis.models import (
    ActionRequest,
    CommandSpec,
    FileWriteAction,
    NetworkPolicy,
    Provenance,
    RiskLevel,
    SkillContract,
)
from xt_aegis.policy import PolicyEngine
from xt_aegis.workspace import IsolatedWorkspace

BoundedText = Annotated[str, Field(max_length=1_024)]

_ERROR_LIMIT = 512


class TrialOutcome(StrEnum):
    """Terminal state of one measured repetition."""

    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class BenchmarkEnvironment(BaseModel):
    """Machine and source identity required to reproduce or reject a comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit: str = Field(max_length=40)
    source_dirty: bool
    operating_system: str = Field(max_length=64)
    release: str = Field(max_length=128)
    architecture: str = Field(max_length=32)
    cpu_count: int = Field(ge=1)
    python_version: str = Field(max_length=32)
    python_implementation: str = Field(max_length=32)
    dependency_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class BenchmarkWorkload(BaseModel):
    """Exact parameters the trials were generated from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    files: int = Field(ge=1, le=100_000)
    file_bytes: int = Field(ge=1, le=10_485_760)
    warmup: int = Field(ge=0, le=1_000)
    trials: int = Field(ge=1, le=10_000)
    seed: int = Field(ge=0)
    timeout_seconds: float = Field(gt=0.0, le=3_600.0)


class BenchmarkTrial(BaseModel):
    """One raw repetition; failures and deadline overruns are retained, never filtered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case: str = Field(max_length=64)
    index: int = Field(ge=1)
    outcome: TrialOutcome
    duration_ms: float = Field(ge=0.0)
    error: BoundedText = ""


class BenchmarkCaseSummary(BaseModel):
    """Distribution of one case; a summary never replaces the raw trials it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case: str = Field(max_length=64)
    description: str = Field(max_length=240)
    trials: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    timed_out: int = Field(ge=0)
    median_ms: float | None = None
    p90_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    stdev_ms: float | None = None


class BenchmarkReport(BaseModel):
    """Schema-valid artifact binding raw trials to one exact profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    project: str = Field(max_length=64)
    project_version: str = Field(max_length=32)
    environment: BenchmarkEnvironment
    workload: BenchmarkWorkload
    reproduction_command: str = Field(max_length=1_024)
    trials: list[BenchmarkTrial] = Field(max_length=100_000)
    summaries: list[BenchmarkCaseSummary] = Field(max_length=64)
    limitations: list[BoundedText] = Field(default_factory=list, max_length=32)


@dataclass(frozen=True)
class BenchmarkCase:
    """One measured operation and the fixture it needs."""

    name: str
    description: str
    factory: Callable[[Path, BenchmarkWorkload], "_MeasuredOperation"]  # noqa: UP037


class _MeasuredOperation:
    """A prepared operation; ``run`` is the only measured call."""

    def __init__(self, run: Callable[[], None], close: Callable[[], None] | None = None) -> None:
        self.run = run
        self.close = close or (lambda: None)


def _percentile(sorted_values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile: deterministic for the small trial counts a laptop profile produces."""

    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    rank = max(1, min(len(sorted_values), int(-(-percentile * len(sorted_values) // 100))))
    return sorted_values[rank - 1]


def _dependency_digest() -> str:
    """Hash the declared dependency contract so two runs cannot be compared across different pins."""

    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "requirements.txt", "uv.lock"):
        candidate = root / name
        if candidate.is_file():
            digest.update(name.encode())
            digest.update(candidate.read_bytes())
    return digest.hexdigest()


def _source_identity() -> tuple[str, bool]:
    root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "", False
    if commit.returncode != 0:
        return "", False
    return commit.stdout.strip()[:40], bool(dirty.stdout.strip())


def environment() -> BenchmarkEnvironment:
    """Collect the machine identity a reviewer needs to accept or reject a comparison."""

    commit, dirty = _source_identity()
    return BenchmarkEnvironment(
        commit=commit,
        source_dirty=dirty,
        operating_system=platform.system(),
        release=platform.release(),
        architecture=platform.machine(),
        cpu_count=os.cpu_count() or 1,
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        dependency_digest=_dependency_digest(),
    )


def _discard(value: object) -> None:
    """Consume a measured return value so the operation signature stays uniform."""

    del value


def _write_template(root: Path, workload: BenchmarkWorkload) -> Path:
    """Create a deterministic template; content depends only on the seed and workload."""

    template = root / "template"
    template.mkdir(parents=True, exist_ok=True)
    for index in range(workload.files):
        payload = f"{workload.seed}:{index}:".encode()
        filler = payload * (workload.file_bytes // len(payload) + 1)
        (template / f"file_{index:05d}.txt").write_bytes(filler[: workload.file_bytes])
    return template


def _workspace(root: Path, workload: BenchmarkWorkload) -> IsolatedWorkspace:
    template = _write_template(root, workload)
    return IsolatedWorkspace.from_template(template, run_root=root / f"run-{time.perf_counter_ns()}")


def _tree_hash_operation(root: Path, workload: BenchmarkWorkload) -> _MeasuredOperation:
    workspace = _workspace(root, workload)
    return _MeasuredOperation(run=lambda: _discard(workspace.hash_tree()))


def _snapshot_operation(root: Path, workload: BenchmarkWorkload) -> _MeasuredOperation:
    workspace = _workspace(root, workload)

    def run() -> None:
        transaction = workspace.begin_transaction()
        transaction.commit()

    return _MeasuredOperation(run=run)


def _rollback_operation(root: Path, workload: BenchmarkWorkload) -> _MeasuredOperation:
    workspace = _workspace(root, workload)

    def run() -> None:
        transaction = workspace.begin_transaction()
        (workspace.root / "file_00000.txt").write_text("mutated", encoding="utf-8")
        if not transaction.rollback():
            raise RuntimeError("rollback did not restore the recorded workspace hash")

    return _MeasuredOperation(run=run)


def _checkpoint_operation(root: Path, workload: BenchmarkWorkload) -> _MeasuredOperation:
    del workload
    store = CheckpointStore(root / "state" / "checkpoints.db")
    recorder = EventRecorder(store, root / "state" / "events.jsonl")
    trace_id = recorder.new_trace_id()
    counter = iter(range(1, 1_000_000))

    def run() -> None:
        recorder.emit(
            trace_id=trace_id,
            thread_id=f"thread:benchmark:{next(counter)}",
            event_type="benchmark.checkpoint",
            payload={"step": "measured"},
        )

    return _MeasuredOperation(run=run)


def _policy_operation(root: Path, workload: BenchmarkWorkload) -> _MeasuredOperation:
    workspace = _workspace(root, workload)
    contract = SkillContract(
        schema_version="1.0",
        name="benchmark_policy",
        description="Deterministic policy evaluation fixture for the benchmark harness.",
        allowed_executables={"python3"},
        allowed_write_paths=["file_00000.txt"],
        network_policy=NetworkPolicy.DENY,
        risk_level=RiskLevel.LOW,
        preconditions=[CommandSpec(description="noop", argv=["python3", "--version"])],
        postconditions=[CommandSpec(description="noop", argv=["python3", "--version"])],
    )
    engine = PolicyEngine(contract, workspace)
    request = ActionRequest(
        thread_id="thread:benchmark",
        action_id="action:benchmark",
        idempotency_key="idem:benchmark:0001",
        provenance=Provenance.OPERATOR,
        action=FileWriteAction(relative_path="file_00000.txt", content="benchmark"),
    )

    def run() -> None:
        engine.validate_request(request)

    return _MeasuredOperation(run=run)


CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase("tree-hash", "Full workspace tree hash", _tree_hash_operation),
    BenchmarkCase("snapshot", "Workspace snapshot creation and commit", _snapshot_operation),
    BenchmarkCase("rollback", "Snapshot rollback with hash verification", _rollback_operation),
    BenchmarkCase("checkpoint-write", "SQLite WAL event append and JSONL persistence", _checkpoint_operation),
    BenchmarkCase("policy-evaluate", "Policy validation of one file-write request", _policy_operation),
)

CASE_NAMES: tuple[str, ...] = tuple(case.name for case in CASES)


def summarize(case: BenchmarkCase, trials: Sequence[BenchmarkTrial]) -> BenchmarkCaseSummary:
    """Aggregate raw trials deterministically; failed and timed-out trials stay counted."""

    case_trials = [trial for trial in trials if trial.case == case.name]
    durations = sorted(trial.duration_ms for trial in case_trials if trial.outcome == TrialOutcome.PASSED)
    return BenchmarkCaseSummary(
        case=case.name,
        description=case.description,
        trials=len(case_trials),
        passed=len(durations),
        failed=sum(1 for trial in case_trials if trial.outcome == TrialOutcome.FAILED),
        timed_out=sum(1 for trial in case_trials if trial.outcome == TrialOutcome.TIMED_OUT),
        median_ms=statistics.median(durations) if durations else None,
        p90_ms=_percentile(durations, 90) if durations else None,
        p95_ms=_percentile(durations, 95) if durations else None,
        p99_ms=_percentile(durations, 99) if durations else None,
        min_ms=durations[0] if durations else None,
        max_ms=durations[-1] if durations else None,
        stdev_ms=statistics.stdev(durations) if len(durations) > 1 else None,
    )


@contextmanager
def _fixture_root() -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix="xt-aegis-benchmark-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _run_case(case: BenchmarkCase, root: Path, workload: BenchmarkWorkload) -> list[BenchmarkTrial]:
    trials: list[BenchmarkTrial] = []
    for index in range(1, workload.warmup + workload.trials + 1):
        case_root = root / f"{case.name}-{index}"
        case_root.mkdir(parents=True, exist_ok=True)
        measured_index = index - workload.warmup
        try:
            operation = case.factory(case_root, workload)
        except Exception as exc:  # setup failure is evidence, not a crash
            if measured_index >= 1:
                trials.append(
                    BenchmarkTrial(
                        case=case.name,
                        index=measured_index,
                        outcome=TrialOutcome.FAILED,
                        duration_ms=0.0,
                        error=f"setup: {type(exc).__name__}: {exc}"[:_ERROR_LIMIT],
                    )
                )
            continue
        started = time.perf_counter()
        outcome = TrialOutcome.PASSED
        error = ""
        try:
            operation.run()
        except Exception as exc:  # a failed trial is retained evidence
            outcome = TrialOutcome.FAILED
            error = f"{type(exc).__name__}: {exc}"[:_ERROR_LIMIT]
        duration_ms = (time.perf_counter() - started) * 1000
        operation.close()
        if outcome == TrialOutcome.PASSED and duration_ms > workload.timeout_seconds * 1000:
            # ponytail: the deadline is observed after the call, not enforced mid-call; an in-process
            # operation cannot be interrupted safely. Subprocess-level enforcement belongs to #10.
            outcome = TrialOutcome.TIMED_OUT
            error = f"exceeded the declared deadline of {workload.timeout_seconds:.3f}s"
        if measured_index >= 1:
            trials.append(
                BenchmarkTrial(
                    case=case.name,
                    index=measured_index,
                    outcome=outcome,
                    duration_ms=duration_ms,
                    error=error,
                )
            )
        if outcome == TrialOutcome.TIMED_OUT:
            break
    return trials


def run_benchmark(
    *,
    workload: BenchmarkWorkload,
    case_names: Sequence[str] | None = None,
    project: str = "XT-Aegis",
    project_version: str | None = None,
) -> BenchmarkReport:
    """Run the selected deterministic cases and return every raw trial with its summary."""

    from xt_aegis import __version__

    selected = [case for case in CASES if case_names is None or case.name in case_names]
    unknown = sorted(set(case_names or ()) - set(CASE_NAMES))
    if unknown:
        raise ValueError(f"unknown benchmark case: {', '.join(unknown)}")
    trials: list[BenchmarkTrial] = []
    with _fixture_root() as root:
        for case in selected:
            trials.extend(_run_case(case, root, workload))
    return BenchmarkReport(
        project=project,
        project_version=project_version or __version__,
        environment=environment(),
        workload=workload,
        reproduction_command=reproduction_command(workload, [case.name for case in selected]),
        trials=trials,
        summaries=[summarize(case, trials) for case in selected],
        limitations=[
            "Results describe only the recorded environment, workload, and source revision.",
            "Wall-clock timings from a shared or virtualized host are not a production performance claim.",
            "The deadline is observed after each repetition; it does not interrupt an in-process call.",
            "Failed and timed-out trials remain in this artifact and are excluded only from the latency "
            "distribution, never from the counts.",
        ],
    )


def reproduction_command(workload: BenchmarkWorkload, case_names: Sequence[str]) -> str:
    """Return the exact command that regenerates this report."""

    parts = ["xt-aegis", "benchmark"]
    for name in case_names:
        parts.extend(["--case", name])
    parts.extend(
        [
            "--files",
            str(workload.files),
            "--file-bytes",
            str(workload.file_bytes),
            "--warmup",
            str(workload.warmup),
            "--trials",
            str(workload.trials),
            "--seed",
            str(workload.seed),
            "--timeout-seconds",
            f"{workload.timeout_seconds:g}",
        ]
    )
    return " ".join(parts)


def format_report(report: BenchmarkReport) -> str:
    """Render a human-readable summary that always shows failure counts next to latency."""

    lines = [
        f"{report.project} {report.project_version} on {report.environment.operating_system} "
        f"{report.environment.architecture}, Python {report.environment.python_version}",
        f"commit {report.environment.commit or 'unknown'}"
        f"{' (dirty)' if report.environment.source_dirty else ''}",
        f"workload: {report.workload.files} files x {report.workload.file_bytes} bytes, "
        f"{report.workload.warmup} warmup, {report.workload.trials} trials, seed {report.workload.seed}",
        "",
        f"{'case':<18}{'ok':>4}{'fail':>6}{'t/o':>5}{'median_ms':>12}{'p95_ms':>10}{'max_ms':>10}",
    ]
    for summary in report.summaries:
        lines.append(
            f"{summary.case:<18}{summary.passed:>4}{summary.failed:>6}{summary.timed_out:>5}"
            f"{_render(summary.median_ms):>12}{_render(summary.p95_ms):>10}{_render(summary.max_ms):>10}"
        )
    lines.extend(["", f"reproduce: {report.reproduction_command}"])
    return "\n".join(lines)


def _render(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def write_report(report: BenchmarkReport, output_dir: str | Path) -> Path:
    """Persist the raw artifact next to nothing else; the file is the evidence."""

    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "benchmark-report.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exercised through the CLI
    from xt_aegis.cli import main as cli_main

    return cli_main(["benchmark", *(argv or sys.argv[1:])])
