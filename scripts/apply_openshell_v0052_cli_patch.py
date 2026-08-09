"""One-shot patch aligning the OpenShell adapter with CLI v0.0.52."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


old_adapter = '''            "--no-auto-providers",
            "--approval-mode",
            "manual",
            "--no-tty",
            "--upload",
            ".:/workspace",
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
'''
new_adapter = '''            "--no-auto-providers",
            "--no-tty",
            "--upload",
            ".:/workspace",
            "--no-keep",
            "--",
            "env",
            "HOME=/home/verifier",
            "PYTHONPATH=/workspace/src",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONUNBUFFERED=1",
            "PYTHONPYCACHEPREFIX=/tmp/pycache",
            "COVERAGE_FILE=/tmp/.coverage",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "MYPY_CACHE_DIR=/tmp/mypy-cache",
            "python",
'''
replace_once(ROOT / "src/xt_aegis/verification.py", old_adapter, new_adapter)

old_expected = '''        "--no-auto-providers",
        "--approval-mode",
        "manual",
        "--no-tty",
        "--upload",
        ".:/workspace",
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
'''
new_expected = '''        "--no-auto-providers",
        "--no-tty",
        "--upload",
        ".:/workspace",
        "--no-keep",
        "--",
        "env",
        "HOME=/home/verifier",
        "PYTHONPATH=/workspace/src",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONUNBUFFERED=1",
        "PYTHONPYCACHEPREFIX=/tmp/pycache",
        "COVERAGE_FILE=/tmp/.coverage",
        "RUFF_CACHE_DIR=/tmp/ruff-cache",
        "MYPY_CACHE_DIR=/tmp/mypy-cache",
        "python",
'''
replace_once(ROOT / "tests/test_verification.py", old_expected, new_expected)
