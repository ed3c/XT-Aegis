from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/xt_aegis/verification.py"
text = PATH.read_text(encoding="utf-8")

if "from collections.abc import Mapping" not in text:
    marker = "from __future__ import annotations\n"
    if marker not in text:
        raise SystemExit("future import marker was not found")
    text = text.replace(marker, marker + "\nfrom collections.abc import Mapping\n", 1)

safe_start = text.index("def _safe_environment(")
safe_end = text.index("\ndef validate_recipe_policy", safe_start)
new_safe = '''def _safe_environment(
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
    """Forward only user-session values required to locate the selected gateway."""

    allowed_keys = ("HOME", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    environment = {key: value for key in allowed_keys if (value := os.environ.get(key))}
    environment["OPENSHELL_TELEMETRY_ENABLED"] = os.environ.get(
        "OPENSHELL_TELEMETRY_ENABLED", "false"
    )
    return environment

'''
text = text[:safe_start] + new_safe + text[safe_end + 1 :]

run_start = text.index("def _run_process(")
run_body = text.index("    started = time.perf_counter()", run_start)
new_signature = '''def _run_process(
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    environment_overrides: Mapping[str, str] | None = None,
) -> CommandEvidence:
'''
text = text[:run_start] + new_signature + text[run_body:]
text = text.replace("            env=_safe_environment(cwd),\n", "            env=_safe_environment(cwd, environment_overrides),\n", 1)

openshell_start = text.index("class OpenShellBackend:")
call_start = text.index("        command = _run_process(", openshell_start)
call_end = text.index("        return BackendExecution", call_start)
new_call = '''        command = _run_process(
            self.preview(recipe, root),
            root.resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
            environment_overrides=_openshell_host_environment(),
        )
'''
text = text[:call_start] + new_call + text[call_end:]

PATH.write_text(text, encoding="utf-8")
