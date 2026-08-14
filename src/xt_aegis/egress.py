"""Default-deny egress decisions and single-use credential injection authorizations.

Nothing here opens a socket. The policy decides whether a destination may be contacted and which resolved
address a caller is allowed to connect to; the caller performs the connection against that pinned address.
Separating the decision from the connection is what makes the rebinding defense testable without a network.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from collections.abc import Callable, Sequence
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

BoundedReason = Annotated[str, Field(max_length=240)]

_MAX_RESOLVED_ADDRESSES = 32


class EgressDecision(StrEnum):
    """Terminal verdict for one destination check."""

    ALLOWED = "allowed"
    DENIED = "denied"


class DenyReason(StrEnum):
    """Machine-readable cause; every deny names exactly one."""

    MALFORMED_URL = "malformed_url"
    SCHEME_NOT_ALLOWED = "scheme_not_allowed"
    USER_INFO_PRESENT = "user_info_present"
    HOST_NOT_ALLOWED = "host_not_allowed"
    PORT_NOT_ALLOWED = "port_not_allowed"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    PATH_NOT_ALLOWED = "path_not_allowed"
    NO_ADDRESS_RESOLVED = "no_address_resolved"
    PRIVATE_ADDRESS = "private_address"
    MIXED_ADDRESS_ANSWER = "mixed_address_answer"
    ADDRESS_CHANGED = "address_changed"
    REDIRECT_NOT_ALLOWED = "redirect_not_allowed"


class EgressRule(BaseModel):
    """One approved destination. Everything not matched by a rule is denied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scheme: Literal["http", "https"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    methods: frozenset[str] = frozenset({"GET", "POST"})
    path_prefixes: tuple[str, ...] = ("/",)
    allow_private_address: bool = False

    @field_validator("host")
    @classmethod
    def canonical_host(cls, value: str) -> str:
        return canonical_host(value)

    @field_validator("methods")
    @classmethod
    def upper_methods(cls, value: frozenset[str]) -> frozenset[str]:
        if not value:
            raise ValueError("an egress rule must allow at least one method")
        return frozenset(method.upper() for method in value)


class EgressRecord(BaseModel):
    """Redacted audit record; a reviewer can reproduce the verdict without the request body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: EgressDecision
    reason: DenyReason | None = None
    method: str = Field(max_length=16)
    scheme: str = Field(max_length=8)
    host: str = Field(max_length=253)
    port: int = Field(ge=0, le=65_535)
    path: str = Field(max_length=512)
    pinned_address: str | None = Field(default=None, max_length=64)
    detail: BoundedReason = ""


class EgressDenied(RuntimeError):
    """Raised when a destination is not approved by the active policy."""

    def __init__(self, record: EgressRecord) -> None:
        super().__init__(f"{record.reason.value if record.reason else 'denied'}: {record.detail}")
        self.record = record


def canonical_host(host: str) -> str:
    """Normalize a hostname so equivalent spellings cannot bypass a rule.

    Case, a trailing dot, and Unicode all produce the same key; a hostname that cannot be encoded as IDNA
    is returned lowercased so it fails the rule comparison instead of raising during policy construction.
    """

    stripped = host.strip().rstrip(".").lower()
    if not stripped:
        return stripped
    try:
        return stripped.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return stripped


def _is_private(address: str) -> bool:
    """Treat loopback, private, link-local, reserved, and the cloud metadata address as private."""

    parsed = ipaddress.ip_address(address)
    if parsed == ipaddress.ip_address("169.254.169.254"):
        return True
    return bool(
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


class EgressPolicy:
    """Default-deny destination policy with a pinned-address contract for the caller."""

    def __init__(
        self,
        rules: Sequence[EgressRule] = (),
        *,
        resolver: Callable[[str], Sequence[str]] | None = None,
        allow_redirects: bool = False,
    ) -> None:
        self.rules = tuple(rules)
        self.allow_redirects = allow_redirects
        self._resolver = resolver
        self.records: list[EgressRecord] = []

    def _record(self, record: EgressRecord) -> EgressRecord:
        self.records.append(record)
        return record

    def _resolve(self, host: str) -> list[str]:
        if self._resolver is None:
            return []
        return list(self._resolver(host))[:_MAX_RESOLVED_ADDRESSES]

    def check(self, url: str, *, method: str = "GET", redirect: bool = False) -> EgressRecord:
        """Return an allow record with a pinned address, or a deny record naming exactly one reason."""

        method = method.upper()
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            return self._record(
                EgressRecord(
                    decision=EgressDecision.DENIED,
                    reason=DenyReason.MALFORMED_URL,
                    method=method,
                    scheme="",
                    host="",
                    port=0,
                    path="",
                    detail="the destination could not be parsed",
                )
            )
        canonical = canonical_host(host or "")
        resolved_port = port or {"http": 80, "https": 443}.get(parsed.scheme, 0)
        observed_path = parsed.path[:512] or "/"

        def build(
            decision: EgressDecision,
            *,
            reason: DenyReason | None,
            detail: str,
            pinned_address: str | None = None,
        ) -> EgressRecord:
            return self._record(
                EgressRecord(
                    decision=decision,
                    reason=reason,
                    method=method,
                    scheme=parsed.scheme,
                    host=canonical,
                    port=resolved_port,
                    path=observed_path,
                    pinned_address=pinned_address,
                    detail=detail,
                )
            )

        def deny(reason: DenyReason, detail: str) -> EgressRecord:
            return build(EgressDecision.DENIED, reason=reason, detail=detail)

        if redirect and not self.allow_redirects:
            return deny(DenyReason.REDIRECT_NOT_ALLOWED, "redirects are denied by default")
        if parsed.username is not None or parsed.password is not None:
            return deny(DenyReason.USER_INFO_PRESENT, "a URL with user-info is never approved")
        if parsed.scheme not in {"http", "https"}:
            return deny(DenyReason.SCHEME_NOT_ALLOWED, f"scheme {parsed.scheme!r} is not approved")
        if not canonical:
            return deny(DenyReason.HOST_NOT_ALLOWED, "the destination has no host")

        host_rules = [rule for rule in self.rules if rule.scheme == parsed.scheme and rule.host == canonical]
        if not host_rules:
            return deny(DenyReason.HOST_NOT_ALLOWED, "no rule approves this host")
        port_rules = [rule for rule in host_rules if rule.port == resolved_port]
        if not port_rules:
            return deny(DenyReason.PORT_NOT_ALLOWED, f"port {resolved_port} is not approved for this host")
        method_rules = [rule for rule in port_rules if method in rule.methods]
        if not method_rules:
            return deny(DenyReason.METHOD_NOT_ALLOWED, f"method {method} is not approved for this host")
        path = parsed.path or "/"
        rule = next(
            (
                candidate
                for candidate in method_rules
                if any(path.startswith(prefix) for prefix in candidate.path_prefixes)
            ),
            None,
        )
        if rule is None:
            return deny(DenyReason.PATH_NOT_ALLOWED, "no rule approves this path")

        addresses = self._resolve(canonical)
        if self._resolver is not None:
            if not addresses:
                return deny(DenyReason.NO_ADDRESS_RESOLVED, "the host resolved to no address")
            private = [address for address in addresses if _is_private(address)]
            if private and len(private) != len(addresses):
                # Diagnosed before the all-private case: a mixed answer is the rebinding signature, and
                # reporting it as a plain private address would hide why the host is suspicious.
                return deny(
                    DenyReason.MIXED_ADDRESS_ANSWER,
                    "the host resolved to both private and public addresses",
                )
            if private and not rule.allow_private_address:
                return deny(
                    DenyReason.PRIVATE_ADDRESS,
                    "the host resolved to a loopback, private, link-local, or metadata address",
                )

        return build(
            EgressDecision.ALLOWED,
            reason=None,
            detail="approved by an explicit rule",
            pinned_address=addresses[0] if addresses else None,
        )

    def require(self, url: str, *, method: str = "GET", redirect: bool = False) -> EgressRecord:
        """Fail closed: return the allow record or raise with the deny record attached."""

        record = self.check(url, method=method, redirect=redirect)
        if record.decision is EgressDecision.DENIED:
            raise EgressDenied(record)
        return record

    def confirm_pinned_address(self, record: EgressRecord, connected_address: str) -> EgressRecord:
        """Reject a connection that reached an address other than the one the decision was made against.

        A resolver answer can change between the policy check and the connection; without this the earlier
        allow decision would silently authorize a different host.
        """

        if record.pinned_address is not None and connected_address == record.pinned_address:
            return record
        return self._record(
            EgressRecord(
                decision=EgressDecision.DENIED,
                reason=DenyReason.ADDRESS_CHANGED,
                method=record.method,
                scheme=record.scheme,
                host=record.host,
                port=record.port,
                path=record.path,
                pinned_address=record.pinned_address,
                detail="the connected address does not match the address the decision was made against",
            )
        )


LOOPBACK_HTTP_RULE_PORTS: tuple[int, ...] = (11_434,)


def loopback_rules(ports: Sequence[int] = LOOPBACK_HTTP_RULE_PORTS) -> tuple[EgressRule, ...]:
    """Rules for a user-operated local provider: loopback only, on explicitly named ports."""

    rules: list[EgressRule] = []
    for port in ports:
        for host in ("localhost", "127.0.0.1"):
            rules.append(
                EgressRule(
                    scheme="http",
                    host=host,
                    port=port,
                    methods=frozenset({"POST"}),
                    path_prefixes=("/api/",),
                    allow_private_address=True,
                )
            )
    return tuple(rules)


class CredentialAuthorization(BaseModel):
    """A single-purpose, short-lived permission to inject one named credential into one exact request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    credential_name: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    tool: str = Field(min_length=1, max_length=64)
    method: str = Field(min_length=1, max_length=16)
    scheme: str = Field(min_length=1, max_length=8)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    path: str = Field(min_length=1, max_length=512)
    argument_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: BoundedReason
    expires_at: float


class CredentialInjectionError(RuntimeError):
    """Raised when an authorization does not match the exact request being made."""


def argument_digest(arguments: object) -> str:
    """Canonical digest of the request arguments an authorization is bound to."""

    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class CredentialBroker:
    """Hold credentials outside the workspace, the environment, argv, prompts, and telemetry.

    A credential is returned only as a header value for one already-approved request, once. The broker
    never writes a credential anywhere; the audit record names the credential, never its value.
    """

    def __init__(
        self,
        credentials: dict[str, str],
        *,
        clock: Callable[[], float] | None = None,
        default_ttl_seconds: float = 60.0,
    ) -> None:
        self._credentials = dict(credentials)
        self._clock = clock or time.monotonic
        self._default_ttl_seconds = default_ttl_seconds
        self._consumed: set[str] = set()
        self.records: list[dict[str, str]] = []

    def _key(self, authorization: CredentialAuthorization) -> str:
        return argument_digest(authorization.model_dump(mode="json"))

    def authorize(
        self,
        *,
        credential_name: str,
        subject: str,
        tool: str,
        record: EgressRecord,
        arguments: object,
        reason: str,
        ttl_seconds: float | None = None,
    ) -> CredentialAuthorization:
        """Bind an injection to the exact approved destination, method, arguments, and expiry."""

        if record.decision is not EgressDecision.ALLOWED:
            raise CredentialInjectionError("a credential cannot be authorized for a denied destination")
        if credential_name not in self._credentials:
            raise CredentialInjectionError(f"unknown credential: {credential_name}")
        ttl = self._default_ttl_seconds if ttl_seconds is None else ttl_seconds
        return CredentialAuthorization(
            credential_name=credential_name,
            subject=subject,
            tool=tool,
            method=record.method,
            scheme=record.scheme,
            host=record.host,
            port=record.port,
            path=record.path,
            argument_digest=argument_digest(arguments),
            reason=reason[:240],
            expires_at=self._clock() + ttl,
        )

    def inject(
        self,
        authorization: CredentialAuthorization,
        *,
        record: EgressRecord,
        arguments: object,
        header: str = "Authorization",
    ) -> dict[str, str]:
        """Return the header for this exact request, once, or fail closed."""

        key = self._key(authorization)
        if key in self._consumed:
            raise CredentialInjectionError("this injection authorization was already used")
        if self._clock() >= authorization.expires_at:
            raise CredentialInjectionError("this injection authorization expired")
        if record.decision is not EgressDecision.ALLOWED:
            raise CredentialInjectionError("the destination is not approved")
        mismatched = [
            field
            for field, expected in (
                ("method", authorization.method),
                ("scheme", authorization.scheme),
                ("host", authorization.host),
                ("port", authorization.port),
                ("path", authorization.path),
            )
            if getattr(record, field) != expected
        ]
        if mismatched:
            raise CredentialInjectionError(
                "the request does not match the authorization: " + ", ".join(mismatched)
            )
        if argument_digest(arguments) != authorization.argument_digest:
            raise CredentialInjectionError("the request arguments do not match the authorization")
        self._consumed.add(key)
        self.records.append(
            {
                "credential_name": authorization.credential_name,
                "subject": authorization.subject,
                "tool": authorization.tool,
                "destination": f"{record.scheme}://{record.host}:{record.port}{record.path}",
                "method": record.method,
                "reason": authorization.reason,
            }
        )
        return {header: self._credentials[authorization.credential_name]}
