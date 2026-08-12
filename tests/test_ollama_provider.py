from __future__ import annotations

import json
from http.client import HTTPMessage
from io import BytesIO
from typing import Any
from urllib.error import URLError
from urllib.request import BaseHandler, HTTPRedirectHandler, ProxyHandler, Request

import pytest
from pydantic import ValidationError

import xt_aegis.providers.ollama as ollama_module
from xt_aegis.proposals import ProposalRequest, ProposalStatus, SamplingProfile
from xt_aegis.providers.ollama import (
    NoRedirectHandler,
    OllamaConfig,
    OllamaHttpResponse,
    OllamaProposalProvider,
    UrllibOllamaTransport,
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
        sampling=SamplingProfile(temperature=0.0, seed=7, context_tokens=8192, max_output_tokens=256),
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
                    "created_at": "2026-08-12T00:00:00Z",
                    "response": "def calculate_tax(amount: float) -> float:\n    return amount * 0.07\n",
                    "done": True,
                    "done_reason": "stop",
                    "context": [1, 2, 3],
                    "total_duration": 2_500_000,
                    "load_duration": 100_000,
                    "prompt_eval_count": 12,
                    "prompt_eval_duration": 900_000,
                    "eval_count": 18,
                    "eval_duration": 1_500_000,
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
        "options": {
            "temperature": 0.0,
            "seed": 7,
            "num_ctx": 8192,
            "num_predict": 256,
        },
    }


def test_ollama_honors_request_level_completion_and_response_budgets() -> None:
    transport = FakeOllamaTransport(
        OllamaHttpResponse(
            status_code=200,
            body=b'{"model":"qwen3:4b","response":"code","done":true,"eval_count":4}',
        )
    )
    provider = OllamaProposalProvider(ollama_config(), transport=transport)

    outcome = provider.propose(
        ProposalRequest(
            task="Propose code.",
            max_prompt_tokens=64,
            max_completion_tokens=17,
            timeout_seconds=1.5,
            max_proposal_bytes=32,
            max_response_bytes=1024,
        )
    )

    assert outcome.status == ProposalStatus.READY
    _, raw_payload, timeout_seconds, max_response_bytes = transport.calls[0]
    assert timeout_seconds == 1.5
    assert max_response_bytes == 1024
    payload = json.loads(raw_payload)
    assert payload["options"]["num_predict"] == 17
    assert payload["options"]["num_ctx"] == 81


def test_ollama_rejects_proposal_larger_than_request_content_budget() -> None:
    transport = FakeOllamaTransport(
        OllamaHttpResponse(
            status_code=200,
            body=b'{"model":"qwen3:4b","response":"12345","done":true}',
        )
    )
    provider = OllamaProposalProvider(ollama_config(), transport=transport)

    outcome = provider.propose(ProposalRequest(task="Propose code.", max_proposal_bytes=4))

    assert outcome.status == ProposalStatus.OVERSIZED
    assert outcome.proposal is None


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
            sampling=SamplingProfile(temperature=0.0, seed=7, context_tokens=8192, max_output_tokens=256),
        )


@pytest.mark.parametrize(
    ("response", "expected_status"),
    [
        (OllamaHttpResponse(200, b"\xff"), ProposalStatus.MALFORMED),
        (OllamaHttpResponse(200, b"not json"), ProposalStatus.MALFORMED),
        (OllamaHttpResponse(200, b"1" + b"0" * 5000), ProposalStatus.MALFORMED),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"qwen3:4b","response":"code","done":"true"}',
            ),
            ProposalStatus.MALFORMED,
        ),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"qwen3:4b","response":"code","done":true,"prompt_eval_count":"12"}',
            ),
            ProposalStatus.MALFORMED,
        ),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"qwen3:4b","response":"code","done":true,"total_duration":Infinity}',
            ),
            ProposalStatus.MALFORMED,
        ),
        (OllamaHttpResponse(200, b'{"done":true}'), ProposalStatus.MALFORMED),
        (
            OllamaHttpResponse(200, b'{"response":"partial","done":false}'),
            ProposalStatus.TRUNCATED,
        ),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"qwen3:4b","response":"partial","done":true,"done_reason":"length"}',
            ),
            ProposalStatus.TRUNCATED,
        ),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"other:latest","response":"code","done":true}',
            ),
            ProposalStatus.MALFORMED,
        ),
        (
            OllamaHttpResponse(
                200,
                b'{"model":"qwen3:4b","response":"code","done":true,"target_path":"outside.py"}',
            ),
            ProposalStatus.MALFORMED,
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
        (URLError(TimeoutError("provider timed out")), ProposalStatus.TIMED_OUT),
        (OSError("password=supersecret"), ProposalStatus.PROVIDER_ERROR),
    ],
)
def test_ollama_transport_failures_are_typed_and_redacted(
    error: Exception,
    expected_status: ProposalStatus,
) -> None:
    provider = OllamaProposalProvider(ollama_config(), transport=FakeOllamaTransport(error=error))

    outcome = provider.propose(ProposalRequest(task="Propose code."))

    assert outcome.status == expected_status
    assert outcome.proposal is None
    assert "supersecret" not in outcome.diagnostic


def test_ollama_profile_metadata_is_redacted() -> None:
    config = ollama_config().model_copy(update={"model": "password=supersecret", "version": "secret=hidden"})
    response = OllamaHttpResponse(
        200,
        b'{"model":"password=supersecret","response":"code","done":true}',
    )

    outcome = OllamaProposalProvider(config, transport=FakeOllamaTransport(response)).propose(
        ProposalRequest(task="Propose code.")
    )

    assert outcome.status == ProposalStatus.READY
    assert "supersecret" not in outcome.profile.model
    assert "hidden" not in outcome.profile.version


class FakeHttpStream:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> FakeHttpStream:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, amount: int) -> bytes:
        return self.body[:amount]


class FakeOpener:
    def __init__(self, stream: FakeHttpStream) -> None:
        self.stream = stream
        self.calls: list[tuple[Request, float]] = []

    def open(self, request: Request, *, timeout: float) -> Any:
        self.calls.append((request, timeout))
        return self.stream


def test_urllib_transport_posts_json_with_a_bounded_read() -> None:
    opener = FakeOpener(FakeHttpStream(b'{"response":"ok","done":true}'))
    transport = UrllibOllamaTransport(opener=opener)

    response = transport.post_json("http://127.0.0.1:11434/api/generate", b'{"model":"qwen3"}', 2.0, 128)

    assert response.status_code == 200
    assert response.body == b'{"response":"ok","done":true}'
    request, timeout = opener.calls[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 2.0


def test_urllib_transport_oversize_becomes_typed_provider_outcome() -> None:
    transport = UrllibOllamaTransport(opener=FakeOpener(FakeHttpStream(b"x" * 17)))
    config = ollama_config().model_copy(update={"max_response_bytes": 16})
    provider = OllamaProposalProvider(config, transport=transport)

    outcome = provider.propose(ProposalRequest(task="Propose code."))

    assert outcome.status == ProposalStatus.OVERSIZED
    assert outcome.proposal is None


def test_default_transport_disables_proxies_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_handlers: tuple[BaseHandler, ...] = ()
    opener = FakeOpener(FakeHttpStream(b"{}"))

    def capture_build_opener(*handlers: BaseHandler) -> FakeOpener:
        nonlocal captured_handlers
        captured_handlers = handlers
        return opener

    monkeypatch.setattr(ollama_module, "build_opener", capture_build_opener)
    UrllibOllamaTransport()

    proxy_handlers = [handler for handler in captured_handlers if isinstance(handler, ProxyHandler)]
    redirect_handlers = [handler for handler in captured_handlers if isinstance(handler, NoRedirectHandler)]
    assert len(proxy_handlers) == 1
    assert vars(proxy_handlers[0])["proxies"] == {}
    assert len(redirect_handlers) == 1
    assert isinstance(redirect_handlers[0], HTTPRedirectHandler)
    redirect_handler: HTTPRedirectHandler = redirect_handlers[0]
    assert (
        redirect_handler.redirect_request(
            Request("http://127.0.0.1"),
            BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "https://example.com",
        )
        is None
    )
