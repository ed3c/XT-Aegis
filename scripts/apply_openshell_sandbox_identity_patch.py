"""One-shot patch aligning all source-bound verification assets with OpenShell's sandbox identity."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_all(path: Path, old: str, new: str, *, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"expected {expected} matches in {path}, found {count}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


replace_all(
    ROOT / "src/xt_aegis/verification.py",
    "HOME=/home/verifier",
    "HOME=/home/sandbox",
    expected=1,
)
replace_all(
    ROOT / "tests/test_verification.py",
    "HOME=/home/verifier",
    "HOME=/home/sandbox",
    expected=1,
)
replace_all(
    ROOT / "tests/test_openshell_assets.py",
    'assert "run_as_user: verifier" in policy',
    'assert "run_as_user: sandbox" in policy',
    expected=1,
)
replace_all(
    ROOT / "tests/test_openshell_assets.py",
    'assert "run_as_group: verifier" in policy',
    'assert "run_as_group: sandbox" in policy',
    expected=1,
)
replace_all(
    ROOT / "tests/test_openshell_assets.py",
    'assert "useradd --create-home --uid 10001 verifier" in dockerfile',
    'assert "useradd --create-home --uid 10001 sandbox" in dockerfile',
    expected=1,
)
replace_all(
    ROOT / "tests/test_openshell_assets.py",
    'assert "install -d -o verifier -g verifier /workspace" in dockerfile',
    'assert "install -d -o sandbox -g sandbox /workspace" in dockerfile',
    expected=1,
)
replace_all(
    ROOT / "tests/test_openshell_assets.py",
    'assert "USER verifier" in dockerfile',
    'assert "USER sandbox" in dockerfile',
    expected=1,
)
replace_all(
    ROOT / "docs/OPENSHELL.md",
    "unprivileged `verifier` user and group",
    "unprivileged `sandbox` user and group",
    expected=1,
)
replace_all(
    ROOT / "docs/OPENSHELL.md",
    "HOME=/home/verifier",
    "HOME=/home/sandbox",
    expected=1,
)
