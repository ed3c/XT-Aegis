"""Optional local Ollama adapter for code-only proposals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xt_aegis.proposals import (
    Proposal,
    ProposalOutcome,
    ProposalRequest,
    ProposalStatus,
    ProviderProfile,
    ProviderUsage,
    SamplingProfile,
)


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
        response = self.transport.post_json(
            f"{self.config.endpoint.rstrip('/')}/api/generate",
            payload,
            self.config.timeout_seconds,
            self.config.max_response_bytes,
        )
        decoded = json.loads(response.body.decode("utf-8"))
        proposal = Proposal(
            kind="replace_file",
            content=decoded["response"],
            profile=profile,
        )
        return ProposalOutcome(
            status=ProposalStatus.READY,
            profile=profile,
            proposal=proposal,
            usage=ProviderUsage(
                prompt_tokens=decoded.get("prompt_eval_count"),
                completion_tokens=decoded.get("eval_count"),
                total_duration_ms=(
                    decoded["total_duration"] / 1_000_000
                    if decoded.get("total_duration") is not None
                    else None
                ),
            ),
        )
