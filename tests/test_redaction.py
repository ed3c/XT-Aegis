from xt_aegis.redaction import redact_text


def test_redacts_common_secrets_and_truncates() -> None:
    value = "api_key=secret-value ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 " + ("x" * 50)
    result = redact_text(value, limit=40)
    assert "secret-value" not in result
    assert "ghp_" not in result
    assert result.endswith("...[truncated]")
