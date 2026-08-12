"""Optional local Ollama adapter for code-only proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from xt_aegis.proposals import (
    Proposal,
    ProposalOutcome,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    ProviderUsage,
    SamplingProfile,
)
from xt_aegis.redaction import redact_text


class OllamaConfig(BaseModel):
    """Trusted local-provider configuration and response bounds."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    sampling: SamplingProfile
    timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    max_response_bytes: int = Field(default=262_144, ge=1, le=1_048_576)

    @field_validator("endpoint")
    @classmethod
    def require_loopback_http_origin(cls, value: str) -> str:
        message = "Ollama endpoint must be a loopback HTTP origin"
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(message) from exc

        if (
            parsed.scheme != "http"
            or host is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(message)

        if host != "localhost":
            try:
                if not ip_address(host).is_loopback:
                    raise ValueError(message)
            except ValueError as exc:
                raise ValueError(message) from exc

        return value.rstrip("/")


class OllamaGenerateResponse(BaseModel):
    """Strict subset of the non-streaming generate response used by the adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model: str | None = None
    created_at: str | None = None
    response: str | None = None
    thinking: str | None = None
    done: bool | None = None
    done_reason: str | None = None
    error: str | None = None
    context: list[int] | None = None
    total_duration: int | float | None = Field(default=None, ge=0, allow_inf_nan=False)
    load_duration: int | float | None = Field(default=None, ge=0, allow_inf_nan=False)
    prompt_eval_count: int | None = Field(default=None, ge=0)
    prompt_eval_duration: int | float | None = Field(default=None, ge=0, allow_inf_nan=False)
    eval_count: int | None = Field(default=None, ge=0)
    eval_duration: int | float | None = Field(default=None, ge=0, allow_inf_nan=False)


@dataclass(frozen=True, slots=True)
class OllamaHttpResponse:
    status_code: int
    body: bytes


class OllamaTransport(Protocol):
    """HTTP boundary; tests replace it without mocking adapter internals."""

    def post_json(
        self,
        url: str,
        payload: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> OllamaHttpResponse:
        """POST one bounded JSON request without redirects or proxies."""


class OllamaResponseTooLarge(RuntimeError):
    """The provider response exceeded the configured byte limit."""


class NoRedirectHandler(HTTPRedirectHandler):
    """Turn redirects into HTTP errors instead of following a new target."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class OllamaHttpStream(Protocol):
    """Minimal urllib response surface used by the bounded transport."""

    status: int

    def __enter__(self) -> OllamaHttpStream: ...

    def __exit__(self, *args: object) -> None: ...

    def read(self, amount: int) -> bytes: ...


class OllamaOpener(Protocol):
    """Injectable stdlib opener boundary for deterministic transport tests."""

    def open(self, request: Request, *, timeout: float) -> OllamaHttpStream: ...


class UrllibOllamaTransport:
    """Bounded local HTTP transport with redirects and environment proxies disabled."""

    def __init__(self, *, opener: OllamaOpener | None = None) -> None:
        self.opener = opener or cast(
            OllamaOpener,
            build_opener(ProxyHandler({}), NoRedirectHandler()),
        )

    def post_json(
        self,
        url: str,
        payload: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> OllamaHttpResponse:
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=timeout_seconds) as response:
                return OllamaHttpResponse(
                    status_code=response.status,
                    body=self._read_bounded(response, max_response_bytes),
                )
        except HTTPError as exc:
            with exc:
                return OllamaHttpResponse(
                    status_code=exc.code,
                    body=self._read_bounded(exc, max_response_bytes),
                )

    @staticmethod
    def _read_bounded(response: Any, max_response_bytes: int) -> bytes:
        body = cast(bytes, response.read(max_response_bytes + 1))
        if len(body) > max_response_bytes:
            raise OllamaResponseTooLarge(f"Ollama response exceeded {max_response_bytes} bytes")
        return body


class OllamaProposalProvider:
    """Translate one non-streaming Ollama response into a provider-neutral outcome."""

    def __init__(
        self,
        config: OllamaConfig,
        *,
        transport: OllamaTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibOllamaTransport()

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        profile = ProviderProfile(
            provider="ollama",
            model=redact_text(self.config.model, limit=160),
            version=redact_text(self.config.version, limit=80),
            sampling=self.config.sampling,
        )
        completion_limit = min(
            self.config.sampling.max_output_tokens,
            request.max_completion_tokens or self.config.sampling.max_output_tokens,
        )
        context_limit = min(
            self.config.sampling.context_tokens,
            (request.max_prompt_tokens or self.config.sampling.context_tokens) + completion_limit,
        )
        response_limit = min(
            self.config.max_response_bytes,
            request.max_response_bytes or self.config.max_response_bytes,
        )
        payload = json.dumps(
            {
                "model": self.config.model,
                "prompt": request.task,
                "stream": False,
                "think": False,
                "options": {
                    "temperature": self.config.sampling.temperature,
                    "seed": self.config.sampling.seed,
                    "num_ctx": context_limit,
                    "num_predict": completion_limit,
                },
            },
            separators=(",", ":"),
        ).encode()
        try:
            response = self.transport.post_json(
                f"{self.config.endpoint}/api/generate",
                payload,
                self.config.timeout_seconds,
                response_limit,
            )
        except OllamaResponseTooLarge as exc:
            return self._failure(ProposalStatus.OVERSIZED, profile, str(exc))
        except TimeoutError as exc:
            return self._failure(ProposalStatus.TIMED_OUT, profile, str(exc))
        except URLError as exc:
            status = (
                ProposalStatus.TIMED_OUT
                if isinstance(exc.reason, TimeoutError)
                else ProposalStatus.PROVIDER_ERROR
            )
            return self._failure(status, profile, str(exc.reason))
        except OSError as exc:
            return self._failure(ProposalStatus.PROVIDER_ERROR, profile, str(exc))

        decoded = self._decode_response(response.body)
        if decoded is None:
            return self._failure(
                ProposalStatus.MALFORMED,
                profile,
                "Ollama response was not valid UTF-8 JSON",
            )

        if not 200 <= response.status_code < 300:
            status = (
                ProposalStatus.REFUSED if 400 <= response.status_code < 500 else ProposalStatus.PROVIDER_ERROR
            )
            return self._failure(
                status,
                profile,
                self._response_error(decoded, response.status_code),
            )

        error = decoded.error
        if error:
            return self._failure(ProposalStatus.REFUSED, profile, error)
        if decoded.done is False or decoded.done_reason == "length":
            return self._failure(
                ProposalStatus.TRUNCATED,
                profile,
                "Ollama response did not reach a completed state",
            )
        content = decoded.response
        if decoded.done is not True or decoded.model != self.config.model or not content:
            return self._failure(
                ProposalStatus.MALFORMED,
                profile,
                "Ollama response omitted required completion fields",
            )

        try:
            proposal = Proposal(
                content=content,
            )
            usage = self._usage(decoded)
        except (TypeError, ValueError, ValidationError):
            return self._failure(
                ProposalStatus.MALFORMED,
                profile,
                "Ollama response contained invalid completion metadata",
            )
        return ProposalOutcome(
            status=ProposalStatus.READY,
            profile=profile,
            proposal=proposal,
            usage=usage,
        )

    @staticmethod
    def _decode_response(body: bytes) -> OllamaGenerateResponse | None:
        try:
            decoded = json.loads(body.decode("utf-8"))
            return OllamaGenerateResponse.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError):
            return None

    @staticmethod
    def _response_error(decoded: OllamaGenerateResponse, status_code: int) -> str:
        error = decoded.error
        if error:
            return f"Ollama HTTP {status_code}: {error}"
        return f"Ollama HTTP {status_code}"

    @staticmethod
    def _usage(decoded: OllamaGenerateResponse) -> ProviderUsage:
        duration = decoded.total_duration
        return ProviderUsage(
            prompt_tokens=decoded.prompt_eval_count,
            completion_tokens=decoded.eval_count,
            total_duration_ms=duration / 1_000_000 if duration is not None else None,
        )

    @staticmethod
    def _failure(
        status: ProposalStatus,
        profile: ProviderProfile,
        diagnostic: str,
    ) -> ProposalOutcome:
        return ProposalOutcome(
            status=status,
            profile=profile,
            diagnostic=redact_text(diagnostic, limit=512),
        )
