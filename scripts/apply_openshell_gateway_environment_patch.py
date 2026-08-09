from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

verification = ROOT / "src/xt_aegis/verification.py"
text = verification.read_text(encoding="utf-8")
text = text.replace(
    '''    return environment

def validate_recipe_policy''',
    '''    return environment


def validate_recipe_policy''',
    1,
)
verification.write_text(text, encoding="utf-8")

tests = ROOT / "tests/test_verification.py"
text = tests.read_text(encoding="utf-8")
if "from collections.abc import Mapping" not in text:
    text = text.replace(
        "from __future__ import annotations\n\n",
        "from __future__ import annotations\n\nfrom collections.abc import Mapping\n",
        1,
    )
old = '''    def fake_run_process(argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> object:
        observed.update(
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
'''
new = '''    def fake_run_process(
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
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one fake process target, found {text.count(old)}")
text = text.replace(old, new)
old_assertion = '''    assert observed["cwd"] == tmp_path.resolve()
    assert ".:/workspace" in observed["argv"]
'''
new_assertion = '''    assert observed["cwd"] == tmp_path.resolve()
    assert observed["environment_overrides"] == verification._openshell_host_environment()
    assert ".:/workspace" in observed["argv"]
'''
if text.count(old_assertion) != 1:
    raise SystemExit("expected one OpenShell cwd assertion")
text = text.replace(old_assertion, new_assertion)
marker = '''def test_openshell_backend_requires_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
'''
new_test = '''def test_openshell_host_environment_is_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/user")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/home/user/.config")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setenv("OPENSHELL_TELEMETRY_ENABLED", "false")
    monkeypatch.setenv("UNRELATED_PRIVATE_VALUE", "must-not-cross")

    environment = verification._openshell_host_environment()

    assert environment == {
        "HOME": "/home/user",
        "XDG_CONFIG_HOME": "/home/user/.config",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        "OPENSHELL_TELEMETRY_ENABLED": "false",
    }
    assert "UNRELATED_PRIVATE_VALUE" not in environment


'''
if new_test not in text:
    if text.count(marker) != 1:
        raise SystemExit("expected OpenShell policy test marker")
    text = text.replace(marker, new_test + marker)
tests.write_text(text, encoding="utf-8")
