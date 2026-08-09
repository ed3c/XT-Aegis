"""One-shot patch aligning runtime paths with the OpenShell Community base."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace(path: Path, old: str, new: str, expected: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"expected {expected} matches in {path}, found {count}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace(
    ROOT / "src/xt_aegis/verification.py",
    "HOME=/home/sandbox",
    "HOME=/sandbox",
)
replace(
    ROOT / "tests/test_verification.py",
    "HOME=/home/sandbox",
    "HOME=/sandbox",
)
replace(
    ROOT / "docs/OPENSHELL.md",
    "HOME=/home/sandbox",
    "HOME=/sandbox",
)
replace(
    ROOT / "docs/OPENSHELL.md",
    "the unprivileged `sandbox` user and group created by `Dockerfile.verifier`;",
    "the unprivileged `sandbox` user and `supervisor` runtime contract supplied by the OpenShell Community base image;",
)
replace(
    ROOT / "docs/OPENSHELL.md",
    "2. builds the verifier image from the selected source revision;",
    "2. builds the verifier image on the OpenShell Community base and records both resolved image identities;",
)
replace(
    ROOT / "docs/OPENSHELL.md",
    "- `/workspace` is a writable disposable copy inside the sandbox, not a read-only host bind mount;",
    "- the OpenShell Community `latest` base tag is mutable; retained evidence records its resolved image identity, while releases should prefer a reviewed digest;\n- `/workspace` is a writable disposable copy inside the sandbox, not a read-only host bind mount;",
)
