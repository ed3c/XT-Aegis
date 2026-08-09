"""One-shot patch for safe OpenShell host gateway environment forwarding."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


verification = ROOT / "src/xt_aegis/verification.py"
replace_once(
    verification,
    '''from __future__ import annotations

import gzip
''',
    '''from __future__ import annotations

from collections.abc import Mapping

import gzip
''',
)

replace_once(
    verification,
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
    """Forward only the user-session values required to locate the selected gateway."""

    allowed_keys = (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
    )
    environment = {
        key: value
        for key in allowed_keys
        if (value := os.environ.get(key))
    }
    environment["OPENSHELL_TELEMETRY_ENABLED"] = os.environ.get(
        "OPENSHELL_TELEMETRY_ENABLED", "false"
    )
    return environment
''',
)

replace_once(
    verification,
    '''def _run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> CommandEvidence:
''',
    '''def _run_process(
    argv: list[str],
    cwd: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    environment_overrides: Mapping[str, str] | None = None,
) -> CommandEvidence:
''',
)

replace_once(
    verification,
    '''            env=_safe_environment(cwd),
''',
    '''            env=_safe_environment(cwd, environment_overrides),
''',
)

replace_once(
    verification,
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
)

verification_tests = ROOT / "tests/test_verification.py"
replace_once(
    verification_tests,
    '''    def fake_run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> object:
        observed.update(
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
''',
    '''    def fake_run_process(
        argv: list[str],
        cwd: Path,
        timeout_seconds: int,
        max_output_bytes: int,
        environment_overrides: Mapping[str, str] | None = None,
    ) -> object:
        observed.update(
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            environment_overrides=environment_overrides,
        )
''',
)

replace_once(
    verification_tests,
    '''from pathlib import Path
''',
    '''from collections.abc import Mapping
from pathlib import Path
''',
)

replace_once(
    verification_tests,
    '''    assert observed["cwd"] == tmp_path.resolve()
    assert ".:/workspace" in observed["argv"]
''',
    '''    assert observed["cwd"] == tmp_path.resolve()
    assert observed["environment_overrides"] == verification._openshell_host_environment()
    assert ".:/workspace" in observed["argv"]
''',
)

insertion_point = '''def test_openshell_backend_requires_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
'''
new_test = '''def test_openshell_host_environment_forwards_gateway_state_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/user/.config")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("OPENSHELL_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross")

    environment = verification._openshell_host_environment()

    assert environment == {
        "HOME": "/home/user",
        "XDG_CONFIG_HOME": "/home/user/.config",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "OPENSHELL_TELEMETRY_ENABLED": "false",
    }
    assert "GITHUB_TOKEN" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment


'''
text = verification_tests.read_text(encoding="utf-8")
if text.count(insertion_point) != 1:
    raise SystemExit("expected OpenShell policy test insertion point")
verification_tests.write_text(text.replace(insertion_point, new_test + insertion_point), encoding="utf-8")
