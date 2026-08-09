"""Best-effort secret redaction before logs are persisted."""

from __future__ import annotations

import re


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\b\s*[:=]\s*([^\s,;]+)"
    ),
)


def redact_text(value: str, *, limit: int = 8_192) -> str:
    """Redact common token forms and cap stored output size."""

    redacted = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    if len(redacted) > limit:
        return redacted[:limit] + "\n...[truncated]"
    return redacted
