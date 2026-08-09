"""Deterministic policy checks kept outside model-generated text."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import PurePosixPath

from xt_aegis.errors import PolicyViolation, WorkspaceSafetyError
from xt_aegis.models import (
    ActionRequest,
    CommandAction,
    CommandSpec,
    FileWriteAction,
    NetworkPolicy,
    Provenance,
    SkillContract,
)
from xt_aegis.workspace import IsolatedWorkspace


_NETWORK_CAPABLE_EXECUTABLES = {
    "curl",
    "wget",
    "ssh",
    "scp",
    "sftp",
    "nc",
    "ncat",
    "telnet",
}
_INTERPRETER_INLINE_CODE_FLAGS = {"-c", "--command"}


class PolicyEngine:
    """Fail-closed validation for structured actions and assertion commands."""

    def __init__(self, contract: SkillContract, workspace: IsolatedWorkspace) -> None:
        self.contract = contract
        self.workspace = workspace

    def validate_request(self, request: ActionRequest) -> None:
        reasons: list[str] = []
        if request.provenance == Provenance.EXTERNAL_CONTENT:
            reasons.append("external or retrieved content cannot directly invoke executable tools")

        if isinstance(request.action, FileWriteAction):
            reasons.extend(self._validate_file_write(request.action))
        elif isinstance(request.action, CommandAction):
            reasons.extend(self._validate_command(request.action.command))

        if reasons:
            raise PolicyViolation(reasons)

    def validate_condition(self, command: CommandSpec) -> None:
        reasons = self._validate_command(command)
        if reasons:
            raise PolicyViolation(reasons)

    def _validate_file_write(self, action: FileWriteAction) -> list[str]:
        reasons: list[str] = []
        encoded_size = len(action.content.encode("utf-8"))
        if encoded_size > self.contract.max_write_bytes:
            reasons.append(
                f"write size {encoded_size} exceeds contract limit {self.contract.max_write_bytes} bytes"
            )

        path = PurePosixPath(action.relative_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            reasons.append("write path must be a normalized relative path")
            return reasons

        if not any(fnmatch.fnmatch(path.as_posix(), pattern) for pattern in self.contract.allowed_write_paths):
            reasons.append(f"write path is not allowed by the skill contract: {path.as_posix()}")

        try:
            target = self.workspace.resolve_relative(path.as_posix())
        except WorkspaceSafetyError as exc:
            reasons.append(str(exc))
            return reasons

        if action.expected_sha256 is not None:
            if not target.is_file():
                reasons.append("expected_sha256 was supplied but target file does not exist")
            else:
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual != action.expected_sha256:
                    reasons.append("target file changed since the action was proposed")
        return reasons

    def _validate_command(self, command: CommandSpec) -> list[str]:
        reasons: list[str] = []
        executable = command.argv[0]
        if "/" in executable or "\\" in executable:
            reasons.append("commands must use a bare executable name")
        if executable not in self.contract.allowed_executables:
            reasons.append(f"executable is not allowlisted: {executable}")

        try:
            self.workspace.resolve_relative(command.cwd)
        except WorkspaceSafetyError as exc:
            reasons.append(str(exc))

        for argument in command.argv:
            for fragment in self.contract.denied_argument_fragments:
                if fragment and fragment in argument:
                    reasons.append(f"argument contains denied control fragment: {fragment!r}")
                    break

        if executable in {"python", "python3", "node", "ruby", "perl", "bash", "sh"}:
            if any(argument in _INTERPRETER_INLINE_CODE_FLAGS for argument in command.argv[1:]):
                reasons.append("inline interpreter code is disabled; use reviewed files or modules")

        if self.contract.network_policy == NetworkPolicy.DENY and executable in _NETWORK_CAPABLE_EXECUTABLES:
            reasons.append(f"network-capable executable denied by network policy: {executable}")

        return reasons
