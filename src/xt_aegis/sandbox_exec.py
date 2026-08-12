"""Execute a validated argv inside a confined sandbox working directory."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import NoReturn


class SandboxExecError(ValueError):
    """Raised when the sandbox launcher receives an unsafe path or command."""


def resolve_workdir(root: str | Path, relative_cwd: str) -> Path:
    """Resolve a recipe working directory without allowing it to escape the uploaded source root."""

    root_path = Path(root).expanduser().resolve(strict=True)
    relative_path = Path(relative_cwd)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise SandboxExecError("sandbox cwd must be a normalized relative path")
    workdir = (root_path / relative_path).resolve(strict=True)
    if not workdir.is_relative_to(root_path) or not workdir.is_dir():
        raise SandboxExecError("sandbox cwd escaped the uploaded source root")
    return workdir


def exec_argv(root: str | Path, relative_cwd: str, argv: list[str]) -> NoReturn:
    """Change to the confined workdir and replace the process without invoking a shell."""

    if not argv or not argv[0].strip():
        raise SandboxExecError("a non-empty argv is required")
    if Path(argv[0]).name != argv[0]:
        raise SandboxExecError("path-qualified executables are not allowed")
    workdir = resolve_workdir(root, relative_cwd)
    os.chdir(workdir)
    os.execvp(argv[0], argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a verified argv inside an uploaded source tree")
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--cwd", default=".")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        exec_argv(args.root, args.cwd, command)
    except (OSError, SandboxExecError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
