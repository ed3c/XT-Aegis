"""Bounded, allowlisted spans that stay local unless a user explicitly configures an exporter."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from xt_aegis.redaction import redact_text

SCHEMA_VERSION = "1.0"

_ATTRIBUTE_VALUE_LIMIT = 256
_ATTRIBUTE_KEY_LIMIT = 64


class SpanName(StrEnum):
    """The span vocabulary; a name outside this set is a contract error, not a free-form label."""

    RUN = "run"
    POLICY_EVALUATE = "policy.evaluate"
    APPROVAL_WAIT = "approval.wait"
    ACTION_EXECUTE = "action.execute"
    ASSERTION_CHECK = "assertion.check"
    WORKSPACE_ROLLBACK = "workspace.rollback"
    CHECKPOINT_PERSIST = "checkpoint.persist"


class SpanStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


#: Attribute keys that may leave the process. Anything else is dropped, not truncated, because an
#: unreviewed key is exactly how prompts, paths, and credentials escape into a telemetry pipeline.
ATTRIBUTE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "action_id",
        "approval_id",
        "backend",
        "check_index",
        "check_kind",
        "description",
        "event_type",
        "exit_code",
        "idempotency_key",
        "kind",
        "outcome",
        "passed",
        "policy_digest",
        "provenance",
        "reason_code",
        "request_digest",
        "request_digest_version",
        "risk_level",
        "rollback_integrity",
        "schema_version",
        "skill",
        "status",
        "step_number",
        "success",
        "thread_id",
    }
)

AttributeValue = str | int | bool


class SpanRecord(BaseModel):
    """One completed span; attributes are already allowlisted, redacted, and length-bounded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    name: SpanName
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    status: SpanStatus
    duration_ms: float = Field(ge=0.0)
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    dropped_attributes: list[str] = Field(default_factory=list, max_length=64)


def sanitize_attributes(attributes: Mapping[str, object]) -> tuple[dict[str, AttributeValue], list[str]]:
    """Keep allowlisted keys, redact and bound their values, and name what was dropped."""

    kept: dict[str, AttributeValue] = {}
    dropped: list[str] = []
    for key, value in attributes.items():
        bounded_key = key[:_ATTRIBUTE_KEY_LIMIT]
        if bounded_key not in ATTRIBUTE_ALLOWLIST or value is None:
            dropped.append(bounded_key)
            continue
        if isinstance(value, bool | int):
            kept[bounded_key] = value
            continue
        kept[bounded_key] = redact_text(str(value), limit=_ATTRIBUTE_VALUE_LIMIT)[:_ATTRIBUTE_VALUE_LIMIT]
    return kept, sorted(dropped)


class SpanHandle:
    """Mutable span state; only trusted runtime code writes to it."""

    def __init__(self, name: SpanName, trace_id: str, span_id: str, parent_span_id: str | None) -> None:
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.status = SpanStatus.OK
        self.attributes: dict[str, object] = {}

    def set(self, **attributes: object) -> None:
        self.attributes.update(attributes)

    def fail(self) -> None:
        self.status = SpanStatus.ERROR


class Telemetry(Protocol):
    """Span emission seam; export never changes authorization or execution results."""

    def span(self, name: SpanName, **attributes: object) -> _SpanContext:
        """Open one span for the current parent."""


class NullTelemetry:
    """Default: telemetry is off, and the span handle still exists so callers stay uniform."""

    def __init__(self) -> None:
        self.trace_id = secrets.token_hex(16)
        self.open_span_ids: list[str] = []

    def span(self, name: SpanName, **attributes: object) -> _SpanContext:
        return _SpanContext(self, name, attributes)

    def _record(self, handle: SpanHandle, duration_ms: float) -> None:
        del handle, duration_ms


class InMemoryTelemetry(NullTelemetry):
    """Local-only recorder used by tests, the replay command, and offline review."""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[SpanRecord] = []

    def _record(self, handle: SpanHandle, duration_ms: float) -> None:
        attributes, dropped = sanitize_attributes(handle.attributes)
        self.spans.append(
            SpanRecord(
                name=handle.name,
                trace_id=handle.trace_id,
                span_id=handle.span_id,
                parent_span_id=handle.parent_span_id,
                status=handle.status,
                duration_ms=duration_ms,
                attributes=attributes,
                dropped_attributes=dropped,
            )
        )

    def hierarchy(self) -> list[tuple[str, SpanName]]:
        """Return (parent name, child name) pairs so a test can assert the shape, not the timing."""

        by_id = {span.span_id: span for span in self.spans}
        pairs: list[tuple[str, SpanName]] = []
        for span in self.spans:
            parent = by_id.get(span.parent_span_id or "")
            pairs.append((parent.name.value if parent is not None else "", span.name))
        return pairs


class OpenTelemetryBridge(NullTelemetry):
    """Forward spans to whatever tracer provider the user configured; XT-Aegis owns no exporter."""

    def __init__(self, tracer_name: str = "xt-aegis") -> None:
        super().__init__()
        from opentelemetry import trace  # local import: the API is optional at runtime

        self._tracer = trace.get_tracer(tracer_name)

    def _record(self, handle: SpanHandle, duration_ms: float) -> None:
        attributes, dropped = sanitize_attributes(handle.attributes)
        span = self._tracer.start_span(handle.name.value)
        for key, value in attributes.items():
            span.set_attribute(key, value)
        span.set_attribute("xt_aegis.trace_id", handle.trace_id)
        span.set_attribute("xt_aegis.span_id", handle.span_id)
        span.set_attribute("xt_aegis.duration_ms", duration_ms)
        span.set_attribute("xt_aegis.dropped_attributes", len(dropped))
        if handle.status == SpanStatus.ERROR:
            span.set_attribute("xt_aegis.status", SpanStatus.ERROR.value)
        span.end()


class _SpanContext:
    """Context manager that assigns parentage from the recorder's open-span stack."""

    def __init__(self, recorder: NullTelemetry, name: SpanName, attributes: Mapping[str, object]) -> None:
        self._recorder = recorder
        self._stack = recorder.open_span_ids
        self.handle = SpanHandle(
            name=name,
            trace_id=recorder.trace_id,
            span_id=secrets.token_hex(8),
            parent_span_id=self._stack[-1] if self._stack else None,
        )
        self.handle.set(**attributes)
        self._started = 0.0

    def __enter__(self) -> SpanHandle:
        self._stack.append(self.handle.span_id)
        self._started = time.perf_counter()
        return self.handle

    def __exit__(self, exc_type: type[BaseException] | None, *_: object) -> Literal[False]:
        duration_ms = (time.perf_counter() - self._started) * 1000
        if exc_type is not None:
            self.handle.fail()
        self._stack.pop()
        self._recorder._record(self.handle, duration_ms)
        return False


@contextmanager
def otlp_exporter(endpoint: str = "http://127.0.0.1:4318/v1/traces") -> Iterator[None]:
    """Opt-in OTLP export; nothing is exported until a user calls this with an explicit endpoint.

    The OpenTelemetry SDK and the OTLP exporter are optional extras. The endpoint is a network
    destination chosen by the user, never by repository text or model output.
    """

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    try:
        yield
    finally:
        processor.shutdown()
