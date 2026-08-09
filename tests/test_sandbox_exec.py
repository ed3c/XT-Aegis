from __future__ import annotations

from pathlib import Path

import pytest

from xt_aegis import sandbox_exec


def test_resolve_workdir_accepts_confined_relative_path(tmp_path: Path) -> None:
    nested = tmp_path / "src"
    nested.mkdir()
    assert sandbox_exec.resolve_workdir(tmp_path, "src") == nested.resolve()


@pytest.mark.parametrize("relative_cwd", ["../escape", "/tmp", "src/../../escape"])
def test_resolve_workdir_rejects_escape(tmp_path: Path, relative_cwd: str) -> None:
    with pytest.raises(sandbox_exec.SandboxExecError):
        sandbox_exec.resolve_workdir(tmp_path, relative_cwd)


def test_exec_argv_uses_execvp_without_shell(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    workdir.mkdir()
    observed: dict[str, object] = {}

    def fake_chdir(path: str | Path) -> None:
        observed["cwd"] = Path(path)

    def fake_execvp(executable: str, argv: list[str]) -> None:
        observed["executable"] = executable
        observed["argv"] = argv
        raise RuntimeError("exec intercepted")

    monkeypatch.setattr(sandbox_exec.os, "chdir", fake_chdir)
    monkeypatch.setattr(sandbox_exec.os, "execvp", fake_execvp)

    with pytest.raises(RuntimeError, match="exec intercepted"):
        sandbox_exec.exec_argv(tmp_path, "project", ["python", "--version"])

    assert observed == {
        "cwd": workdir.resolve(),
        "executable": "python",
        "argv": ["python", "--version"],
    }


def test_exec_argv_rejects_path_qualified_executable(tmp_path: Path) -> None:
    with pytest.raises(sandbox_exec.SandboxExecError, match="path-qualified"):
        sandbox_exec.exec_argv(tmp_path, ".", ["/usr/bin/python", "--version"])
