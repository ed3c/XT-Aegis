"""Host and Origin rejection paths, driven through the SDK's own middleware.

The tests deliberately do not reimplement the validation rules. A test against a copy of the rules proves
the copy is right; what matters is whether the middleware *the server is configured with* rejects the
request, so every case here builds the real `TransportSecurityMiddleware` from the real settings object.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from xt_aegis import mcp_server
from xt_aegis.mcp_transport import (
    TransportGuard,
    TransportSecurityUnavailable,
    build_transport_guard,
    require_transport_security,
    sdk_version,
)

pytest.importorskip("mcp", reason="the MCP extra is not installed")

from mcp.server.transport_security import TransportSecurityMiddleware

HOST = "127.0.0.1"
PORT = 8765


def _request(headers: dict[str, str]) -> Any:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers.items()],
    }
    return Request(scope)


def _rejection(headers: dict[str, str], guard: TransportGuard | None = None) -> Any:
    """Return the middleware's response, or ``None`` when it admits the request."""

    guard = guard or build_transport_guard(host=HOST, port=PORT)
    middleware = TransportSecurityMiddleware(guard.as_settings())
    complete = {"content-type": "application/json", **headers}
    return asyncio.run(middleware.validate_request(_request(complete), is_post=True))


def test_the_declared_bind_address_is_admitted() -> None:
    assert _rejection({"host": f"{HOST}:{PORT}"}) is None


def test_every_loopback_spelling_of_the_bind_address_is_admitted() -> None:
    """Refusing `localhost` because the flag said an address pushes operators toward a wildcard."""

    for name in ("127.0.0.1", "localhost", "[::1]"):
        assert _rejection({"host": f"{name}:{PORT}"}) is None, name


def test_a_foreign_host_header_is_rejected() -> None:
    response = _rejection({"host": "evil.example.com"})

    assert response is not None
    assert response.status_code == 421


def test_a_dns_rebinding_request_is_rejected() -> None:
    """The attack: a page on an attacker name whose DNS answer is loopback, reaching a loopback server."""

    response = _rejection(
        {"host": "rebind.attacker.example:8765", "origin": "http://rebind.attacker.example:8765"}
    )

    assert response is not None
    assert response.status_code == 421


def test_a_foreign_origin_is_rejected_even_on_an_allowed_host() -> None:
    response = _rejection({"host": f"{HOST}:{PORT}", "origin": "https://evil.example.com"})

    assert response is not None
    assert response.status_code == 403


def test_the_right_host_on_the_wrong_port_is_rejected() -> None:
    """A page served from another port is another origin; treating it as the same one is the hole."""

    response = _rejection({"host": f"{HOST}:9999"})

    assert response is not None


def test_a_missing_host_header_is_rejected() -> None:
    response = _rejection({})

    assert response is not None


def test_the_sdk_admits_a_request_with_no_origin() -> None:
    """Recorded, not asserted as sufficient: the SDK treats an absent Origin as same-origin.

    Host validation is therefore the enforced gate, and `docs/MCP_TRANSPORT.md` says so rather than
    implying that Origin protects non-browser clients.
    """

    assert _rejection({"host": f"{HOST}:{PORT}"}) is None


def test_protection_is_off_when_no_settings_are_supplied() -> None:
    """The defect this slice closes: the SDK's default is no validation at all."""

    middleware = TransportSecurityMiddleware()
    response = asyncio.run(
        middleware.validate_request(
            _request({"host": "evil.example.com", "content-type": "application/json"}), is_post=True
        )
    )

    assert response is None


def test_the_guard_carries_the_port_on_every_entry() -> None:
    guard = build_transport_guard(host=HOST, port=PORT)

    assert all(entry.endswith(f":{PORT}") for entry in guard.allowed_hosts)
    assert all(entry.endswith(f":{PORT}") for entry in guard.allowed_origins)
    assert f"http://{HOST}:{PORT}" in guard.allowed_origins


def test_a_non_loopback_bind_allows_only_the_name_it_was_given() -> None:
    guard = build_transport_guard(host="10.0.0.5", port=PORT)

    assert guard.allowed_hosts == (f"10.0.0.5:{PORT}",)


def test_an_extra_host_is_allowed_for_a_reverse_proxy() -> None:
    guard = build_transport_guard(host=HOST, port=PORT, extra_hosts=("aegis.internal",))

    assert f"aegis.internal:{PORT}" in guard.allowed_hosts


def test_the_installed_sdk_accepts_transport_security() -> None:
    from mcp.server import MCPServer

    require_transport_security(MCPServer.run_streamable_http_async)


def test_an_sdk_without_the_parameter_fails_closed() -> None:
    def legacy_runner(*, host: str = "127.0.0.1", port: int = 8000) -> None: ...

    with pytest.raises(TransportSecurityUnavailable, match="does not accept transport_security"):
        require_transport_security(legacy_runner)


def test_http_refuses_to_start_without_an_enforceable_runner() -> None:
    class ServerWithoutHttp:
        def run(self, **kwargs: Any) -> None:  # pragma: no cover - must not be reached
            raise AssertionError("the server must not start")

    with pytest.raises(TransportSecurityUnavailable, match="no streamable-http runner"):
        mcp_server._run_server(ServerWithoutHttp(), transport="streamable-http", host=HOST, port=PORT)


def test_http_passes_the_guard_to_the_sdk() -> None:
    captured: dict[str, Any] = {}

    class RecordingServer:
        def run_streamable_http_async(
            self, *, host: str = "", port: int = 0, transport_security: Any = None
        ) -> None:  # pragma: no cover - signature only
            ...

        def run(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    mcp_server._run_server(
        RecordingServer(), transport="streamable-http", host=HOST, port=PORT, max_request_bytes=4096
    )

    settings = captured["transport_security"]
    assert settings.enable_dns_rebinding_protection is True
    assert f"{HOST}:{PORT}" in settings.allowed_hosts
    assert captured["max_request_body_size"] == 4096


def test_stdio_does_not_require_a_guard() -> None:
    """stdio has no Host header and is not reachable from a browser."""

    started: list[str] = []

    class StdioOnlyServer:
        def run(self, **kwargs: Any) -> None:
            started.append("run")

    mcp_server._run_server(StdioOnlyServer(), transport="stdio", host=HOST, port=PORT)

    assert started == ["run"]


def test_the_sdk_version_is_reportable() -> None:
    assert sdk_version() not in {"", "not installed"}
