from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/xt_aegis/verification.py"
text = PATH.read_text(encoding="utf-8")

replacements = [
    (
        "from __future__ import annotations\n\nimport gzip\n",
        "from __future__ import annotations\n\nfrom collections.abc import Mapping\n\nimport gzip\n",
    ),
    (
        '''def _safe_environment(root: Path) -> dict[str, str]:
    home = root / ".xt-aegis" / "verification-home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(root / "src"),
        "PYTHONPYCACHEPREFIX": str(home / "pycache"),
        "COVERAGE_FILE": str(home / ".coverage"),
        "RUFF_CACHE_DIR": str(home / "ruff-cache"),
        "MYPY_CACHE_DIR": str(home / "mypy-cache"),
    }
''',
        '''def _safe_environment(
    root: Path,
    environment_overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    home = root / ".xt-aegis" / "verification-home"
    home.mkdir(parents=True, exist_ok=True)
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(root / "src"),
        "PYTHONPYCACHEPREFIX": str(home / "pycache"),
        "COVERAGE_FILE": str(home / ".coverage"),
        "RUFF_CACHE_DIR": str(home / "ruff-cache"),
        "MYPY_CACHE_DIR": str(home / "mypy-cache"),
    }
    if environment_overrides:
        environment.update(environment_overrides)
    return environment


def _openshell_host_environment() -> dict[str, str]:
    allowed_keys = ("HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    environment = {key: value for key in allowed_keys if (value := os.environ.get(key))}
    environment["OPENSHELL_TELEMETRY_ENABLED"] = os.environ.get(
        "OPENSHELL_TELEMETRY_ENABLED", "false"
    )
    return environment
''',
    ),
    (
        "def _run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> CommandEvidence:\n",
        '''def _run_process(
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    environment_overrides: Mapping[str, str] | None = None,
) -> CommandEvidence:
''',
    ),
    ("            env=_safe_environment(cwd),\n", "            env=_safe_environment(cwd, environment_overrides),\n"),
    (
        '''        command = _run_process(
            self.preview(recipe, root),
            root.resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
        )
''',
        '''        command = _run_process(
            self.preview(recipe, root),
            root.resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
            environment_overrides=_openshell_host_environment(),
        )
''',
    ),
]

for old, new in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"expected one patch target, found {text.count(old)}")
    text = text.replace(old, new)

PATH.write_text(text, encoding="utf-8")
