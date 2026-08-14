from __future__ import annotations

import pytest

from xt_aegis.egress import (
    CredentialAuthorization,
    CredentialBroker,
    CredentialInjectionError,
    DenyReason,
    EgressDecision,
    EgressDenied,
    EgressPolicy,
    EgressRule,
    argument_digest,
    canonical_host,
    loopback_rules,
)

PUBLIC_RULE = EgressRule(
    scheme="https",
    host="api.example.com",
    port=443,
    methods=frozenset({"POST"}),
    path_prefixes=("/v1/",),
)


def _policy(*, addresses: list[str] | None = None, allow_redirects: bool = False) -> EgressPolicy:
    resolver = None if addresses is None else (lambda _host: addresses)
    return EgressPolicy([PUBLIC_RULE], resolver=resolver, allow_redirects=allow_redirects)


def test_everything_is_denied_without_a_matching_rule() -> None:
    policy = EgressPolicy([])

    record = policy.check("https://api.example.com/v1/chat", method="POST")

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.HOST_NOT_ALLOWED


def test_an_approved_destination_is_allowed_and_recorded() -> None:
    policy = _policy(addresses=["93.184.216.34"])

    record = policy.require("https://api.example.com/v1/chat", method="POST")

    assert record.decision is EgressDecision.ALLOWED
    assert record.pinned_address == "93.184.216.34"
    assert policy.records[-1] == record


@pytest.mark.parametrize(
    ("url", "method", "reason"),
    [
        ("https://evil.example.com/v1/chat", "POST", DenyReason.HOST_NOT_ALLOWED),
        ("https://api.example.com:8443/v1/chat", "POST", DenyReason.PORT_NOT_ALLOWED),
        ("https://api.example.com/v1/chat", "DELETE", DenyReason.METHOD_NOT_ALLOWED),
        ("https://api.example.com/admin", "POST", DenyReason.PATH_NOT_ALLOWED),
        ("http://api.example.com/v1/chat", "POST", DenyReason.HOST_NOT_ALLOWED),
        ("ftp://api.example.com/v1/chat", "POST", DenyReason.SCHEME_NOT_ALLOWED),
        ("https://user:pass@api.example.com/v1/chat", "POST", DenyReason.USER_INFO_PRESENT),
    ],
)
def test_destination_variants_are_denied_with_one_named_reason(
    url: str, method: str, reason: DenyReason
) -> None:
    record = _policy().check(url, method=method)

    assert record.decision is EgressDecision.DENIED
    assert record.reason is reason


@pytest.mark.parametrize(
    "host",
    ["API.EXAMPLE.COM", "api.example.com.", "API.example.com."],
)
def test_equivalent_host_spellings_match_the_same_rule(host: str) -> None:
    record = _policy(addresses=["93.184.216.34"]).check(f"https://{host}/v1/chat", method="POST")

    assert record.decision is EgressDecision.ALLOWED
    assert record.host == "api.example.com"


def test_a_unicode_host_is_canonicalized_before_matching() -> None:
    assert canonical_host("ExAmPlé.com.") == canonical_host("xn--exampl-gva.com")
    record = _policy().check("https://examplé.com/v1/chat", method="POST")

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.HOST_NOT_ALLOWED
    assert record.host.startswith("xn--")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "169.254.169.254",
        "::1",
        "fe80::1",
        "0.0.0.0",
    ],
)
def test_a_private_or_metadata_answer_is_denied(address: str) -> None:
    record = _policy(addresses=[address]).check("https://api.example.com/v1/chat", method="POST")

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.PRIVATE_ADDRESS


def test_a_mixed_public_and_private_answer_is_denied() -> None:
    record = _policy(addresses=["93.184.216.34", "127.0.0.1"]).check(
        "https://api.example.com/v1/chat", method="POST"
    )

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.MIXED_ADDRESS_ANSWER


def test_a_host_that_resolves_to_nothing_is_denied() -> None:
    record = _policy(addresses=[]).check("https://api.example.com/v1/chat", method="POST")

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.NO_ADDRESS_RESOLVED


def test_a_rebound_address_between_check_and_connect_is_denied() -> None:
    policy = _policy(addresses=["93.184.216.34"])
    allowed = policy.require("https://api.example.com/v1/chat", method="POST")

    confirmed = policy.confirm_pinned_address(allowed, "127.0.0.1")

    assert confirmed.decision is EgressDecision.DENIED
    assert confirmed.reason is DenyReason.ADDRESS_CHANGED
    assert policy.confirm_pinned_address(allowed, "93.184.216.34") is allowed


def test_a_redirect_is_denied_by_default_and_allowed_only_when_configured() -> None:
    denied = _policy(addresses=["93.184.216.34"]).check(
        "https://api.example.com/v1/chat", method="POST", redirect=True
    )
    assert denied.reason is DenyReason.REDIRECT_NOT_ALLOWED

    permitted = _policy(addresses=["93.184.216.34"], allow_redirects=True).check(
        "https://api.example.com/v1/chat", method="POST", redirect=True
    )
    assert permitted.decision is EgressDecision.ALLOWED


def test_a_redirect_to_a_denied_host_still_fails_closed() -> None:
    policy = _policy(addresses=["93.184.216.34"], allow_redirects=True)

    record = policy.check("https://evil.example.com/v1/chat", method="POST", redirect=True)

    assert record.decision is EgressDecision.DENIED
    assert record.reason is DenyReason.HOST_NOT_ALLOWED


def test_require_raises_with_the_deny_record_attached() -> None:
    with pytest.raises(EgressDenied) as excinfo:
        _policy().require("https://evil.example.com/v1/chat", method="POST")

    assert excinfo.value.record.reason is DenyReason.HOST_NOT_ALLOWED


def test_loopback_rules_allow_only_the_declared_local_provider_surface() -> None:
    policy = EgressPolicy(loopback_rules(), resolver=lambda _host: ["127.0.0.1"])

    assert policy.check("http://127.0.0.1:11434/api/generate", method="POST").decision is (
        EgressDecision.ALLOWED
    )
    assert policy.check("http://127.0.0.1:11434/admin", method="POST").reason is DenyReason.PATH_NOT_ALLOWED
    assert policy.check("http://127.0.0.1:8080/api/generate", method="POST").reason is (
        DenyReason.PORT_NOT_ALLOWED
    )
    assert policy.check("http://198.51.100.7:11434/api/generate", method="POST").reason is (
        DenyReason.HOST_NOT_ALLOWED
    )


def _broker(clock_values: list[float] | None = None) -> tuple[CredentialBroker, EgressPolicy]:
    ticks = iter(clock_values or [0.0] * 20)
    broker = CredentialBroker({"provider": "secret-token-value"}, clock=lambda: next(ticks))
    return broker, _policy(addresses=["93.184.216.34"])


def test_a_credential_is_injected_only_for_the_exact_authorized_request() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    arguments = {"model": "m", "prompt_digest": "abc"}
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments=arguments,
        reason="one bounded proposal call",
    )

    headers = broker.inject(authorization, record=record, arguments=arguments)

    assert headers == {"Authorization": "secret-token-value"}
    assert broker.records[-1]["credential_name"] == "provider"
    assert "secret-token-value" not in str(broker.records)


def test_an_authorization_cannot_be_reused() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    arguments = {"model": "m"}
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments=arguments,
        reason="one call",
    )
    broker.inject(authorization, record=record, arguments=arguments)

    with pytest.raises(CredentialInjectionError, match="already used"):
        broker.inject(authorization, record=record, arguments=arguments)


def test_an_authorization_cannot_cover_different_arguments() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments={"model": "m"},
        reason="one call",
    )

    with pytest.raises(CredentialInjectionError, match="arguments do not match"):
        broker.inject(authorization, record=record, arguments={"model": "other"})


def test_an_authorization_cannot_cover_a_different_destination() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments={"model": "m"},
        reason="one call",
    )
    other = EgressPolicy(
        [PUBLIC_RULE.model_copy(update={"path_prefixes": ("/v2/",)})],
        resolver=lambda _host: ["93.184.216.34"],
    ).require("https://api.example.com/v2/chat", method="POST")

    with pytest.raises(CredentialInjectionError, match="does not match the authorization"):
        broker.inject(authorization, record=other, arguments={"model": "m"})


def test_an_expired_authorization_is_refused() -> None:
    broker, policy = _broker(clock_values=[0.0, 61.0, 61.0])
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments={"model": "m"},
        reason="one call",
    )

    with pytest.raises(CredentialInjectionError, match="expired"):
        broker.inject(authorization, record=record, arguments={"model": "m"})


def test_a_denied_destination_cannot_receive_a_credential() -> None:
    broker, policy = _broker()
    denied = policy.check("https://evil.example.com/v1/chat", method="POST")

    with pytest.raises(CredentialInjectionError, match="denied destination"):
        broker.authorize(
            credential_name="provider",
            subject="user:test",
            tool="proposal-adapter",
            record=denied,
            arguments={},
            reason="attempt",
        )


def test_an_unknown_credential_cannot_be_authorized() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")

    with pytest.raises(CredentialInjectionError, match="unknown credential"):
        broker.authorize(
            credential_name="absent",
            subject="user:test",
            tool="proposal-adapter",
            record=record,
            arguments={},
            reason="attempt",
        )


def test_audit_records_never_contain_the_credential_value() -> None:
    broker, policy = _broker()
    record = policy.require("https://api.example.com/v1/chat", method="POST")
    arguments = {"model": "m"}
    authorization = broker.authorize(
        credential_name="provider",
        subject="user:test",
        tool="proposal-adapter",
        record=record,
        arguments=arguments,
        reason="one call",
    )
    broker.inject(authorization, record=record, arguments=arguments)

    serialized = str(broker.records) + authorization.model_dump_json() + str(policy.records)
    assert "secret-token-value" not in serialized


def test_the_argument_digest_is_canonical_and_order_independent() -> None:
    assert argument_digest({"a": 1, "b": 2}) == argument_digest({"b": 2, "a": 1})
    assert argument_digest({"a": 1}) != argument_digest({"a": 2})


def test_an_authorization_is_a_frozen_typed_contract() -> None:
    with pytest.raises(ValueError):
        CredentialAuthorization(
            credential_name="provider",
            subject="user:test",
            tool="proposal-adapter",
            method="POST",
            scheme="https",
            host="api.example.com",
            port=443,
            path="/v1/chat",
            argument_digest="not-a-digest",
            reason="one call",
            expires_at=1.0,
        )


def test_the_local_provider_call_is_refused_when_the_policy_denies_it() -> None:
    from xt_aegis.proposals import ProposalRequest, ProposalStatus, SamplingProfile
    from xt_aegis.providers.ollama import OllamaConfig, OllamaProposalProvider

    class RejectingTransport:
        def post_json(
            self, url: str, payload: bytes, timeout_seconds: float, max_response_bytes: int
        ) -> object:
            raise AssertionError(f"the transport must not be reached for {url}")

    provider = OllamaProposalProvider(
        OllamaConfig(
            endpoint="http://127.0.0.1:11434",
            model="test-model",
            version="0.0.0",
            sampling=SamplingProfile(temperature=0.0, seed=1, context_tokens=2048, max_output_tokens=128),
        ),
        transport=RejectingTransport(),
        egress=EgressPolicy([]),
    )

    outcome = provider.propose(ProposalRequest(task="propose one bounded change"))

    assert outcome.status is ProposalStatus.PROVIDER_ERROR
    assert "host_not_allowed" in outcome.diagnostic
