"""Owned temporary workspaces with snapshot-based transactional rollback."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from xt_aegis.errors import WorkspaceSafetyError

_OWNERSHIP_MARKER = ".xt-aegis-owned"
_IGNORED_HASH_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


class IsolatedWorkspace:
    """A workspace XT-Aegis created and may safely restore or delete."""

    def __init__(self, *, root: Path, run_root: Path, ownership_token: str) -> None:
        self.root = root.resolve()
        self.run_root = run_root.resolve()
        self.ownership_token = ownership_token
        self._assert_owned()

    @classmethod
    def from_template(cls, template: str | Path, run_root: str | Path | None = None) -> IsolatedWorkspace:
        template_path = Path(template).resolve()
        if not template_path.is_dir():
            raise WorkspaceSafetyError(f"template is not a directory: {template_path}")

        if run_root is None:
            created_run_root = Path(tempfile.mkdtemp(prefix="xt-aegis-run-"))
        else:
            created_run_root = Path(run_root).resolve()
            created_run_root.mkdir(parents=True, exist_ok=False)

        workspace_root = created_run_root / "workspace"
        shutil.copytree(template_path, workspace_root, symlinks=False)
        ownership_token = uuid.uuid4().hex
        (workspace_root / _OWNERSHIP_MARKER).write_text(ownership_token, encoding="utf-8")
        return cls(root=workspace_root, run_root=created_run_root, ownership_token=ownership_token)

    def _assert_owned(self) -> None:
        if self.root == Path(self.root.anchor) or self.root == Path.home().resolve():
            raise WorkspaceSafetyError("refusing to operate on a filesystem root or home directory")
        if self.root.is_symlink():
            raise WorkspaceSafetyError("workspace root cannot be a symlink")
        marker = self.root / _OWNERSHIP_MARKER
        try:
            current = marker.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorkspaceSafetyError("workspace ownership marker is missing") from exc
        if current != self.ownership_token:
            raise WorkspaceSafetyError("workspace ownership marker does not match")
        try:
            self.root.relative_to(self.run_root)
        except ValueError as exc:
            raise WorkspaceSafetyError("workspace must be contained by its run root") from exc

    def resolve_relative(self, relative_path: str) -> Path:
        if relative_path in {".", "./"}:
            return self.root
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
            raise WorkspaceSafetyError(f"unsafe relative path: {relative_path}")
        candidate = (self.root / Path(*pure.parts)).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceSafetyError(f"path escapes workspace: {relative_path}") from exc
        return candidate

    def hash_tree(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.root.rglob("*"), key=lambda item: item.as_posix()):
            relative = path.relative_to(self.root)
            if _OWNERSHIP_MARKER in relative.parts or any(
                part in _IGNORED_HASH_PARTS for part in relative.parts
            ):
                continue
            if path.is_symlink():
                digest.update(b"L\0")
                digest.update(relative.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(os.readlink(path).encode("utf-8"))
            elif path.is_file():
                digest.update(b"F\0")
                digest.update(relative.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def begin_transaction(self) -> WorkspaceTransaction:
        self._assert_owned()
        snapshot_parent = Path(tempfile.mkdtemp(prefix="snapshot-", dir=self.run_root))
        snapshot_root = snapshot_parent / "workspace"
        shutil.copytree(self.root, snapshot_root, symlinks=True)
        return WorkspaceTransaction(
            workspace=self, snapshot_parent=snapshot_parent, snapshot_root=snapshot_root
        )


class WorkspaceTransaction:
    """One snapshot that can be committed or restored exactly once."""

    def __init__(self, *, workspace: IsolatedWorkspace, snapshot_parent: Path, snapshot_root: Path) -> None:
        self.workspace = workspace
        self.snapshot_parent = snapshot_parent
        self.snapshot_root = snapshot_root
        self.before_sha256 = workspace.hash_tree()
        self._closed = False

    def commit(self) -> None:
        self._ensure_open()
        shutil.rmtree(self.snapshot_parent)
        self._closed = True

    def rollback(self) -> bool:
        self._ensure_open()
        self.workspace._assert_owned()
        if not self.snapshot_root.is_dir():
            raise WorkspaceSafetyError("snapshot is missing")
        shutil.rmtree(self.workspace.root)
        shutil.copytree(self.snapshot_root, self.workspace.root, symlinks=True)
        shutil.rmtree(self.snapshot_parent)
        self._closed = True
        self.workspace._assert_owned()
        return self.workspace.hash_tree() == self.before_sha256

    def _ensure_open(self) -> None:
        if self._closed:
            raise WorkspaceSafetyError("transaction is already closed")
