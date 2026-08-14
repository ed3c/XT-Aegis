"""Fail-closed transport security for the MCP HTTP surface.

The SDK ships DNS-rebinding protection and turns it *off* when no settings are supplied:

    # If not specified, disable DNS rebinding protection by default for backwards compatibility
    self.settings = settings or TransportSecuritySettings(enable_dns_rebinding_protection=False)

Passing nothing therefore reads as "no opinion" and means "no validation". This module makes the opinion
explicit and refuses to start the HTTP transport at all when the installed SDK cannot accept it — starting
unprotected because a parameter is missing is the outcome worth preventing.

Binding to loopback is not the protection people assume. A page in the user's own browser can resolve an
attacker-controlled name to 127.0.0.1 and reach a loopback server; what stops it is the server checking the
`Host` header it was given, which is what this configures.
"""

from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from typing import Any

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


class TransportSecurityUnavailable(RuntimeError):
    """Raised when the installed SDK cannot enforce Host and Origin validation."""


@dataclass(frozen=True)
class TransportGuard:
    """The allowlists a local HTTP deployment is willing to answer to."""

    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...]

    def as_settings(self) -> Any:
        """Build the SDK's settings object, importing it only when the HTTP transport is used."""

        from mcp.server.transport_security import TransportSecuritySettings

        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(self.allowed_hosts),
            allowed_origins=list(self.allowed_origins),
        )


def _host_forms(host: str) -> tuple[str, ...]:
    """Every spelling of one bind address a client may legitimately send.

    A server bound to a loopback address answers to all of loopback's names, and refusing `localhost`
    because the flag said `127.0.0.1` would push operators toward a wildcard instead.
    """

    if host in LOOPBACK_HOSTS:
        return LOOPBACK_HOSTS
    return (host,)


def build_transport_guard(*, host: str, port: int, extra_hosts: tuple[str, ...] = ()) -> TransportGuard:
    """Derive the allowlists from the address the server was told to bind.

    Every entry carries the declared port. A bare hostname is not accepted: `Host: localhost` from a page
    served on another port is a different origin, and treating it as the same one is the rebinding case.
    """

    names = tuple(dict.fromkeys((*_host_forms(host), *extra_hosts)))
    hosts = tuple(f"{name}:{port}" for name in names)
    origins = tuple(f"{scheme}://{name}:{port}" for name in names for scheme in ("http", "https"))
    return TransportGuard(allowed_hosts=hosts, allowed_origins=origins)


def require_transport_security(runner: Any) -> None:
    """Refuse to serve HTTP when the SDK will not take the settings.

    The check is on the callable that will actually run, not on a version string, because a version string
    is a claim about the package and this is a question about the function being called.
    """

    try:
        parameters = signature(runner).parameters
    except (TypeError, ValueError) as exc:  # pragma: no cover - exotic callables only
        raise TransportSecurityUnavailable(
            "cannot inspect the MCP HTTP runner, so Host validation cannot be confirmed"
        ) from exc
    if "transport_security" not in parameters:
        raise TransportSecurityUnavailable(
            "the installed MCP SDK does not accept transport_security; refusing to serve HTTP without "
            "Host and Origin validation. Use --transport stdio, or install a supported SDK with: "
            'pip install "xt-aegis[mcp]"'
        )


def sdk_version() -> str:
    """The installed SDK version, for the compatibility matrix and for `doctor` output."""

    from importlib import metadata

    try:
        return metadata.version("mcp")
    except metadata.PackageNotFoundError:
        return "not installed"
