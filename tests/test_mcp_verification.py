from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from xt_aegis import mcp_server
from xt_aegis.verification_models import BackendName


class FakeFastMCP:
    def __init__(self, name: str, **settings: Any) -> None:
        self.name = name
        self.settings = settings
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
            self.tools[function.__name__] = function
            return function

        return decorator


def _write_registry(root: Path) -> Path:
    payload = {
        "schema_version": "2.0",
        "project": "XT-Aegis",
        "version": "0.test",
        "maturity": "test",
        "license": "MIT",
        "repository": "https://example.invalid/XT-Aegis",
        "verification_contract": {
            "executable_allowlist": ["python"],
            "default_backend": "auto",
            "strong_backends": ["openshell", "podman", "docker"],
            "unsafe_local_requires_explicit_opt_in": True,
            "environment_allowlist": [],
        },
        "claims": [
            {
                "id": "test-claim",
                "claim": "A test claim.",
                "status": "implemented",
                "evidence": ["PROJECT_EVIDENCE.json"],
                "verification": {
                    "argv": ["python", "--version"],
                    "cwd": ".",
                    "timeout_seconds": 30,
                    "expected_exit_codes": [0],
                    "network": "deny",
                    "max_output_bytes": 4096,
                    "artifacts": [],
                },
                "expected": {"status": "verified", "assertions": {}},
                "limitations": [],
            }
        ],
    }
    path = root / "PROJECT_EVIDENCE.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_mcp_is_read_only_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp.server import fastmcp

    monkeypatch.setattr(fastmcp, "FastMCP", FakeFastMCP)
    registry = _write_registry(tmp_path)
    server = mcp_server.build_server(registry_path=registry)
    assert isinstance(server, FakeFastMCP)
    assert server.settings["stateless_http"] is True
    assert server.settings["json_response"] is True
    assert "verification_verify_claim" not in server.tools
    assert "verification_verify_all" not in server.tools
    capabilities = server.tools["project_capabilities"]()
    assert capabilities["execution_enabled"] is False
    claims = server.tools["verification_list_claims"]()
    assert claims[0]["id"] == "test-claim"


def test_mcp_execution_tools_require_explicit_user_opt_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mcp.server import fastmcp

    monkeypatch.setattr(fastmcp, "FastMCP", FakeFastMCP)
    registry = _write_registry(tmp_path)
    server = mcp_server.build_server(
        registry_path=registry,
        allow_execution=True,
        backend=BackendName.UNSAFE_LOCAL,
        output_root=tmp_path / "out",
    )
    assert "verification_verify_claim" in server.tools
    result = server.tools["verification_verify_claim"]("test-claim")
    assert result["status"] == "verified"
    assert (tmp_path / "out/test-claim/verification-result.json").is_file()


def test_execution_enabled_mcp_rejects_non_loopback_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mcp.server import fastmcp

    monkeypatch.setattr(fastmcp, "FastMCP", FakeFastMCP)
    registry = _write_registry(tmp_path)
    with pytest.raises(ValueError, match="loopback"):
        mcp_server.build_server(
            registry_path=registry,
            allow_execution=True,
            backend=BackendName.UNSAFE_LOCAL,
            host="0.0.0.0",
        )
