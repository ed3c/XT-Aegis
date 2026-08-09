"""One-shot source patch used to update large files through CI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected one match in {path}, found {text.count(old)}")
    path.write_text(text.replace(old, new), encoding="utf-8")


old_preview = '''    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        executable = shutil.which("openshell") or "openshell"
        image = os.getenv("XT_AEGIS_OPENSHELL_IMAGE", _DEFAULT_IMAGE)
        return [
            executable,
            "sandbox",
            "create",
            "--from",
            image,
            "--policy",
            str(self._policy_path(root)),
            "--cpu",
            "1",
            "--memory",
            "1Gi",
            "--no-keep",
            "--",
            *recipe.argv,
        ]
'''

new_preview = '''    def preview(self, recipe: VerificationRecipe, root: Path) -> list[str]:
        executable = shutil.which("openshell") or "openshell"
        image = os.getenv("XT_AEGIS_OPENSHELL_IMAGE", _DEFAULT_IMAGE)
        root_string = str(root.resolve())
        return [
            executable,
            "sandbox",
            "create",
            "--from",
            image,
            "--policy",
            str(self._policy_path(root)),
            "--cpu",
            "1",
            "--memory",
            "1Gi",
            "--no-auto-providers",
            "--approval-mode",
            "manual",
            "--no-tty",
            "--upload",
            f"{root_string}:/workspace",
            "--env",
            "PYTHONPATH=/workspace/src",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--env",
            "COVERAGE_FILE=/tmp/.coverage",
            "--env",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "--env",
            "MYPY_CACHE_DIR=/tmp/mypy-cache",
            "--no-keep",
            "--",
            "python",
            "-m",
            "xt_aegis.sandbox_exec",
            "--root",
            "/workspace",
            "--cwd",
            recipe.cwd,
            "--",
            *recipe.argv,
        ]
'''

replace_once(ROOT / "src/xt_aegis/verification.py", old_preview, new_preview)

old_expected = '''    assert preview == [
        "/usr/bin/openshell",
        "sandbox",
        "create",
        "--from",
        "ghcr.io/ed3c/xt-aegis-verifier:0.2.0",
        "--policy",
        str(policy),
        "--cpu",
        "1",
        "--memory",
        "1Gi",
        "--no-keep",
        "--",
        "python",
        "--version",
    ]
'''

new_expected = '''    assert preview == [
        "/usr/bin/openshell",
        "sandbox",
        "create",
        "--from",
        "ghcr.io/ed3c/xt-aegis-verifier:0.2.0",
        "--policy",
        str(policy),
        "--cpu",
        "1",
        "--memory",
        "1Gi",
        "--no-auto-providers",
        "--approval-mode",
        "manual",
        "--no-tty",
        "--upload",
        f"{tmp_path.resolve()}:/workspace",
        "--env",
        "PYTHONPATH=/workspace/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--env",
        "COVERAGE_FILE=/tmp/.coverage",
        "--env",
        "RUFF_CACHE_DIR=/tmp/ruff-cache",
        "--env",
        "MYPY_CACHE_DIR=/tmp/mypy-cache",
        "--no-keep",
        "--",
        "python",
        "-m",
        "xt_aegis.sandbox_exec",
        "--root",
        "/workspace",
        "--cwd",
        ".",
        "--",
        "python",
        "--version",
    ]
'''

replace_once(ROOT / "tests/test_verification.py", old_expected, new_expected)
