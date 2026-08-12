from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from xt_aegis.proposals import ProposalRequest, ProposalStatus, SamplingProfile
from xt_aegis.providers.ollama import (
    OllamaConfig,
    OllamaHttpResponse,
    OllamaProposalProvider,
)


class FakeOllamaTransport:
    def __init__(
        self,
        response: OllamaHttpResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, bytes, float, int]] = []

    def post_json(
        self,
        url: str,
        payload: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> OllamaHttpResponse:
        self.calls.append((url, payload, timeout_seconds, max_response_bytes))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def ollama_config() -> OllamaConfig:
    return OllamaConfig(
        endpoint="http://127.0.0.1:11434",
        model="qwen3:4b",
        version="0.11.0",
        sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
        timeout_seconds=3.0,
        max_response_bytes=4096,
    )


def test_ollama_code_only_response_becomes_ready_proposal() -> None:
    transport = FakeOllamaTransport(
        OllamaHttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "model": "qwen3:4b",
                    "response": "def calculate_tax(amount: float) -> float:\n    return amount * 0.07\n",
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 2_500_000,
                    "prompt_eval_count": 12,
                    "eval_count": 18,
                }
            ).encode(),
        )
    )
    config = ollama_config()
    provider = OllamaProposalProvider(config, transport=transport)

    outcome = provider.propose(ProposalRequest(task="Replace the tax implementation."))

    assert outcome.status == ProposalStatus.READY
    assert outcome.proposal is not None
    assert outcome.proposal.content.startswith("def calculate_tax")
    assert outcome.profile.provider == "ollama"
    assert outcome.profile.model == "qwen3:4b"
    assert outcome.profile.version == "0.11.0"
    assert outcome.usage.prompt_tokens == 12
    assert outcome.usage.completion_tokens == 18
    assert outcome.usage.total_duration_ms == 2.5
    assert len(transport.calls) == 1
    url, raw_payload, timeout_seconds, max_response_bytes = transport.calls[0]
    assert url == "http://127.0.0.1:11434/api/generate"
    assert timeout_seconds == 3.0
    assert max_response_bytes == 4096
    payload = json.loads(raw_payload)
    assert payload == {
        "model": "qwen3:4b",
        "prompt": "Replace the tax implementation.",
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "seed": 7, "num_predict": 256},
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://ollama.com",
        "http://example.com:11434",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434/proxy",
        "http://127.0.0.1:11434?token=secret",
    ],
)
def test_ollama_config_rejects_non_local_or_credential_bearing_endpoint(
    endpoint: str,
) -> None:
    with pytest.raises(ValidationError, match="loopback HTTP origin"):
        OllamaConfig(
            endpoint=endpoint,
            model="qwen3:4b",
            version="0.11.0",
            sampling=SamplingProfile(temperature=0.0, seed=7, max_output_tokens=256),
        )


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (OllamaHttpResponse(200, b"\xff"), ProposalStatus.MALFORMED),
        (OllamaHttpResponse(200, b"not json"), ProposalStatus.MALFORMED),
        (OllamaHttpResponse(200, b'{"done":true}'), ProposalStatus.MALFORMED),
        (
            OllamaHttpResponse(200, b'{"response":"partial","done":false}'),
            ProposalStatus.TRUNCATED,
        ),
        (
            OllamaHttpResponse(400, b'{"error":"request refused"}'),
            ProposalStatus.REFUSED,
        ),
        (
            OllamaHttpResponse(503, b'{"error":"provider unavailable"}'),
            ProposalStatus.PROVIDER_ERROR,
        ),
    ],
)
def test_ollama_failures_return_typed_outcomes_without_proposals(
    response: OllamaHttpResponse,
    expected_status: ProposalStatus,
) -> None:
    provider = OllamaProposalProvider(ollama_config(), transport=FakeOllamaTransport(response))

    outcome = provider.propose(ProposalRequest(task="Propose code."))

    assert outcome.status == expected_status
    assert outcome.proposal is None
    assert outcome.diagnostic


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TimeoutError("provider timed out"), ProposalStatus.TIMED_OUT),
        (OSError("password=supersecret"), ProposalStatus.PROVIDER_ERROR),
    ],
)
def test_ollama_transport_failures_are_typed_and_redacted(
    error: Exception,
    expected_status: ProposalStatus,
) -> None:
    provider = OllamaProposalProvider(
        ollama_config(), transport=FakeOllamaTransport(error=error)
    )

    outcome = provider.propose(ProposalRequest(task="Propose code."))

    assert outcome.status == expected_status
    assert outcome.proposal is None
    assert "supersecret" not in outcome.diagnostic
