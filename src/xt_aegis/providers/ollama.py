"""Optional local Ollama adapter for code-only proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

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


class OllamaProposalProvider:
    """Translate one non-streaming Ollama response into a provider-neutral outcome."""

    def __init__(self, config: OllamaConfig, *, transport: OllamaTransport) -> None:
        self.config = config
        self.transport = transport

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        profile = ProviderProfile(
            provider="ollama",
            model=self.config.model,
            version=self.config.version,
            sampling=self.config.sampling,
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
                    "num_predict": self.config.sampling.max_output_tokens,
                },
            },
            separators=(",", ":"),
        ).encode()
        try:
            response = self.transport.post_json(
                f"{self.config.endpoint}/api/generate",
                payload,
                self.config.timeout_seconds,
                self.config.max_response_bytes,
            )
        except TimeoutError as exc:
            return self._failure(ProposalStatus.TIMED_OUT, profile, str(exc))
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
                ProposalStatus.REFUSED
                if 400 <= response.status_code < 500
                else ProposalStatus.PROVIDER_ERROR
            )
            return self._failure(
                status,
                profile,
                self._response_error(decoded, response.status_code),
            )

        error = decoded.get("error")
        if isinstance(error, str) and error:
            return self._failure(ProposalStatus.REFUSED, profile, error)
        if decoded.get("done") is False:
            return self._failure(
                ProposalStatus.TRUNCATED,
                profile,
                "Ollama response did not reach a completed state",
            )
        content = decoded.get("response")
        if decoded.get("done") is not True or not isinstance(content, str) or not content:
            return self._failure(
                ProposalStatus.MALFORMED,
                profile,
                "Ollama response omitted required completion fields",
            )

        try:
            proposal = Proposal(
                kind="replace_file",
                content=content,
                profile=profile,
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
    def _decode_response(body: bytes) -> dict[str, object] | None:
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def _response_error(decoded: dict[str, object], status_code: int) -> str:
        error = decoded.get("error")
        if isinstance(error, str) and error:
            return f"Ollama HTTP {status_code}: {error}"
        return f"Ollama HTTP {status_code}"

    @staticmethod
    def _usage(decoded: dict[str, object]) -> ProviderUsage:
        def optional_count(field: str) -> int | None:
            value = decoded.get(field)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"invalid Ollama counter: {field}")
            return value

        duration = decoded.get("total_duration")
        if isinstance(duration, bool) or (
            duration is not None and not isinstance(duration, (int, float))
        ):
            raise ValueError("invalid Ollama duration")
        return ProviderUsage(
            prompt_tokens=optional_count("prompt_eval_count"),
            completion_tokens=optional_count("eval_count"),
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
