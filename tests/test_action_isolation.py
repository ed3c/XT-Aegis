from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from xt_aegis.action_backend import (
    CONTAINER_WORKSPACE,
    ActionBackendName,
    IsolationReadiness,
    IsolationUnavailableError,
    OciActionBackend,
    UnsafeLocalActionBackend,
    select_action_backend,
)
from xt_aegis.checkpoint import CheckpointStore
from xt_aegis.events import EventRecorder
from xt_aegis.models import (
    ActionRequest,
    CommandAction,
    CommandSpec,
    CompiledSkill,
    ExecutionReasonCode,
    ExecutionStatus,
    NetworkPolicy,
    Provenance,
    RiskLevel,
    SkillContract,
)
from xt_aegis.runner import HarnessRunner
from xt_aegis.workspace import IsolatedWorkspace

ACTION_IMAGE = "python:3.12-slim"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "image", "inspect", ACTION_IMAGE],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


requires_docker = pytest.mark.skipif(
    not _docker_available(),
    reason=f"a local Docker daemon with {ACTION_IMAGE} is required for live isolation evidence",
)


class UnreadyBackend:
    name = ActionBackendName.DOCKER
    strong_isolation = True

    def readiness(self, workspace_root: Path) -> IsolationReadiness:
        del workspace_root
        return IsolationReadiness(False, "the runtime socket is unreachable")

    def host_argv(self, argv: list[str], *, workspace_root: Path, relative_cwd: str) -> list[str]:
        raise AssertionError("an unready backend must never be asked to build a command")

    def host_cwd(self, workspace_root: Path, relative_cwd: str) -> Path:
        raise AssertionError("an unready backend must never be asked for a working directory")


def _contract(*, requires_isolation: bool, argv: list[str]) -> SkillContract:
    return SkillContract(
        schema_version="1.0",
        name="isolation_fixture",
        description="Deterministic fixture for the strong-isolation action backend tests.",
        allowed_executables={"python3"},
        allowed_write_paths=["app.py"],
        network_policy=NetworkPolicy.DENY,
        risk_level=RiskLevel.LOW,
        requires_isolation=requires_isolation,
        preconditions=[],
        postconditions=[],
    )


def _runner(
    tmp_path: Path,
    *,
    backend: object,
    requires_isolation: bool = True,
    argv: list[str] | None = None,
) -> HarnessRunner:
    template = tmp_path / "template"
    template.mkdir(parents=True, exist_ok=True)
    (template / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    workspace = IsolatedWorkspace.from_template(template, run_root=tmp_path / "run")
    store = CheckpointStore(tmp_path / "state" / "checkpoints.db")
    skill = CompiledSkill(
        contract=_contract(requires_isolation=requires_isolation, argv=argv or ["python3", "-V"]),
        markdown_body="fixture",
        source_path="isolation.SKILL.md",
        source_sha256="d" * 64,
    )
    return HarnessRunner(
        skill=skill,
        workspace=workspace,
        checkpoint_store=store,
        event_recorder=EventRecorder(store, tmp_path / "state" / "events.jsonl"),
        action_backend=backend,  # type: ignore[arg-type]
    )


def _script(runner: HarnessRunner, name: str, source: str) -> list[str]:
    """Write a script into the owned workspace; the container sees it through the bind mount."""

    (runner.workspace.root / name).write_text(source, encoding="utf-8")
    return ["python3", name]


def _command_request(argv: list[str], *, key: str, exit_codes: set[int] | None = None) -> ActionRequest:
    return ActionRequest(
        thread_id="thread.isolation.001",
        action_id="isolation.command",
        idempotency_key=key,
        actor_id="user:test",
        provenance=Provenance.OPERATOR,
        action=CommandAction(
            command=CommandSpec(
                description="isolation fixture command",
                argv=argv,
                expected_exit_codes=exit_codes or {0},
                timeout_seconds=120.0,
            )
        ),
    )


def test_a_contract_requiring_isolation_fails_closed_on_a_weak_backend(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=UnsafeLocalActionBackend())

    result = runner.execute(_command_request(["python3", "-V"], key="isolation-weak-0001"))

    assert result.status == ExecutionStatus.BLOCKED
    assert result.reason_code == ExecutionReasonCode.ISOLATION_UNAVAILABLE
    assert result.isolation_verdict is False
    assert result.rolled_back is False


def test_a_contract_requiring_isolation_fails_closed_on_an_unready_backend(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=UnreadyBackend())

    result = runner.execute(_command_request(["python3", "-V"], key="isolation-unready-0001"))

    assert result.status == ExecutionStatus.BLOCKED
    assert result.reason_code == ExecutionReasonCode.ISOLATION_UNAVAILABLE
    assert "socket is unreachable" in " ".join(result.policy_reasons)


def test_isolation_verdict_is_reported_separately_from_rollback_integrity(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=UnsafeLocalActionBackend(), requires_isolation=False)

    argv = _script(runner, "noop.py", "raise SystemExit(0)\n")
    result = runner.execute(_command_request(argv, key="isolation-verdict-0001"))

    assert result.isolation_backend == "unsafe-local"
    assert result.isolation_verdict is False
    assert result.rollback_integrity is None or isinstance(result.rollback_integrity, bool)


def test_auto_never_selects_unsafe_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _value: None)

    with pytest.raises(IsolationUnavailableError, match="no strong action-execution backend is ready"):
        select_action_backend(ActionBackendName.AUTO, tmp_path)


def test_explicit_unsafe_local_selection_is_still_possible(tmp_path: Path) -> None:
    backend = select_action_backend(ActionBackendName.UNSAFE_LOCAL, tmp_path)

    assert backend.name is ActionBackendName.UNSAFE_LOCAL
    assert backend.strong_isolation is False


def test_the_container_argv_denies_network_and_mounts_only_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv = OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE).host_argv(
        ["python3", "-V"], workspace_root=workspace, relative_cwd="."
    )

    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "--read-only" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
    mounts = [item for item in argv if item.startswith("type=bind")]
    assert mounts == [f"type=bind,src={workspace},dst={CONTAINER_WORKSPACE}"]
    assert argv[-2:] == ["python3", "-V"]


def test_a_traversal_working_directory_is_refused_before_a_mount_is_built(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backend = OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE)

    with pytest.raises(IsolationUnavailableError, match="escaped the owned workspace"):
        backend.host_argv(["python3", "-V"], workspace_root=workspace, relative_cwd="../..")


@requires_docker
def test_live_container_runs_the_command_inside_the_workspace_mount(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))

    argv = _script(
        runner,
        "read_app.py",
        "import pathlib\nprint(pathlib.Path('app.py').read_text().strip())\n",
    )
    result = runner.execute(_command_request(argv, key="isolation-live-0001"))

    assert result.status == ExecutionStatus.SUCCEEDED, result.action_stderr
    assert "VALUE = 1" in result.action_stdout
    assert result.isolation_verdict is True
    assert result.isolation_backend == "docker"


@requires_docker
def test_live_container_runs_as_a_non_root_user(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))
    argv = _script(runner, "whoami.py", "import os\nprint('uid', os.getuid())\n")

    result = runner.execute(_command_request(argv, key="isolation-live-0007"))

    assert result.status == ExecutionStatus.SUCCEEDED, result.action_stderr
    assert "uid 0" not in result.action_stdout
    assert f"uid {os.getuid()}" in result.action_stdout


@requires_docker
def test_live_container_cannot_write_outside_the_approved_mount(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))

    argv = _script(
        runner,
        "escape.py",
        "import pathlib\n"
        "pathlib.Path('/etc/xt-aegis-escape.txt').write_text('escaped')\n"
        "print('wrote outside')\n",
    )
    result = runner.execute(_command_request(argv, key="isolation-live-0002"))

    assert not outside.exists()
    assert not (tmp_path / "etc").exists()
    assert "wrote outside" not in result.action_stdout
    assert result.status == ExecutionStatus.ROLLED_BACK
    assert "Read-only file system" in result.action_stderr or "Permission denied" in result.action_stderr


@requires_docker
def test_live_container_cannot_read_a_host_secret_canary(tmp_path: Path) -> None:
    canary = tmp_path / "host-secret.txt"
    canary.write_text("canary-value-must-not-be-read\n", encoding="utf-8")
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))

    argv = _script(
        runner,
        "read_canary.py",
        f"import pathlib\nprint(pathlib.Path({str(canary)!r}).read_text())\n",
    )
    result = runner.execute(_command_request(argv, key="isolation-live-0003"))

    assert "canary-value-must-not-be-read" not in result.action_stdout
    assert "canary-value-must-not-be-read" not in result.action_stderr
    assert result.status == ExecutionStatus.ROLLED_BACK
    assert "FileNotFoundError" in result.action_stderr


@requires_docker
def test_live_container_has_no_network(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))

    argv = _script(
        runner,
        "dial.py",
        "import socket\n"
        "socket.setdefaulttimeout(5)\n"
        "socket.create_connection(('93.184.216.34', 80))\n"
        "print('connected')\n",
    )
    result = runner.execute(_command_request(argv, key="isolation-live-0004"))

    assert "connected" not in result.action_stdout
    assert result.status == ExecutionStatus.ROLLED_BACK
    assert "Network is unreachable" in result.action_stderr or "OSError" in result.action_stderr


@requires_docker
def test_live_container_mutation_is_rolled_back_inside_the_mount(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))
    original = (runner.workspace.root / "app.py").read_text(encoding="utf-8")

    argv = _script(
        runner,
        "mutate.py",
        "import pathlib\npathlib.Path('app.py').write_text('MUTATED\\n')\nraise SystemExit(3)\n",
    )
    result = runner.execute(_command_request(argv, key="isolation-live-0005"))

    assert result.status == ExecutionStatus.ROLLED_BACK
    assert result.rollback_integrity is True
    assert result.isolation_verdict is True
    assert (runner.workspace.root / "app.py").read_text(encoding="utf-8") == original


@requires_docker
def test_live_container_leaves_no_container_behind(tmp_path: Path) -> None:
    runner = _runner(tmp_path, backend=OciActionBackend(ActionBackendName.DOCKER, image=ACTION_IMAGE))

    runner.execute(_command_request(["python3", "-V"], key="isolation-live-0006"))

    listed = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"ancestor={ACTION_IMAGE}", "--format", "{{.ID}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.stdout.strip() == ""
