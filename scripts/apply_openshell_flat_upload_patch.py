"""One-shot patch for OpenShell flat source upload semantics."""

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
    '''        executable = shutil.which("openshell") or "openshell"
        image = os.getenv("XT_AEGIS_OPENSHELL_IMAGE", _DEFAULT_IMAGE)
        root_string = str(root.resolve())
        return [
''',
    '''        executable = shutil.which("openshell") or "openshell"
        image = os.getenv("XT_AEGIS_OPENSHELL_IMAGE", _DEFAULT_IMAGE)
        return [
''',
)
replace_once(
    verification,
    '''            "--upload",
            f"{root_string}:/workspace",
''',
    '''            "--upload",
            ".:/workspace",
''',
)
replace_once(
    verification,
    '''        command = _run_process(
            self.preview(recipe, root),
            (root / recipe.cwd).resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
        )
''',
    '''        command = _run_process(
            self.preview(recipe, root),
            root.resolve(),
            recipe.timeout_seconds,
            recipe.max_output_bytes,
        )
''',
)

verification_tests = ROOT / "tests/test_verification.py"
replace_once(
    verification_tests,
    '''        "--upload",
        f"{tmp_path.resolve()}:/workspace",
''',
    '''        "--upload",
        ".:/workspace",
''',
)

# Prove that host-side upload resolution starts at the checkout root even when
# the recipe itself runs from a nested directory inside the sandbox.
needle = '''def test_openshell_backend_requires_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
'''
addition = '''def test_openshell_backend_runs_host_command_from_source_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    policy = tmp_path / "verification/policies/openshell.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_text("version: 1\\nnetwork_policies: {}\\n", encoding="utf-8")
    nested = tmp_path / "tests"
    nested.mkdir()
    monkeypatch.setattr(shutil, "which", lambda value: "/usr/bin/openshell" if value == "openshell" else None)
    observed: dict[str, object] = {}

    def fake_run_process(
        argv: list[str], cwd: Path, timeout_seconds: int, max_output_bytes: int
    ) -> object:
        observed.update(
            argv=argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        return verification.CommandEvidence(
            argv=argv,
            cwd=str(cwd),
            exit_code=0,
            duration_ms=1.0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(verification, "_run_process", fake_run_process)
    recipe = VerificationRecipe(argv=["python", "--version"], cwd="tests")
    OpenShellBackend().run(recipe, tmp_path)

    assert observed["cwd"] == tmp_path.resolve()
    assert ".:/workspace" in observed["argv"]
    assert observed["argv"][-7:] == [
        "--root",
        "/workspace",
        "--cwd",
        "tests",
        "--",
        "python",
        "--version",
    ]


'''
text = verification_tests.read_text(encoding="utf-8")
if text.count(needle) != 1:
    raise SystemExit("expected OpenShell policy test insertion point")
verification_tests.write_text(text.replace(needle, addition + needle), encoding="utf-8")
