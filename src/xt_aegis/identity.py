"""Versioned canonical identities for requests and deterministic policy bindings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import cast

from pydantic import BaseModel

from xt_aegis.models import ActionRequest, CompiledSkill

REQUEST_DIGEST_VERSION = "1.0"


def _normalize(value: object) -> object:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        normalized: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise TypeError("canonical object keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (set, frozenset)):
        values = cast(set[object] | frozenset[object], value)
        normalized_items = [_normalize(item) for item in values]
        return sorted(normalized_items, key=_canonical_sort_key)
    if isinstance(value, (list, tuple)):
        values = cast(list[object] | tuple[object, ...], value)
        return [_normalize(item) for item in values]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _canonical_sort_key(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_json_bytes(value: object) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def policy_digest(skill: CompiledSkill) -> str:
    return _sha256(
        {
            "digest_version": REQUEST_DIGEST_VERSION,
            "contract": skill.contract,
        }
    )


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    version: str
    digest: str
    policy_digest: str

    @classmethod
    def from_request(cls, request: ActionRequest, *, skill: CompiledSkill) -> RequestIdentity:
        bound_policy_digest = policy_digest(skill)
        request_payload = request.model_dump(mode="python", exclude={"approval_id"})
        digest = _sha256(
            {
                "digest_version": REQUEST_DIGEST_VERSION,
                "policy_digest": bound_policy_digest,
                "request": request_payload,
            }
        )
        return cls(
            version=REQUEST_DIGEST_VERSION,
            digest=digest,
            policy_digest=bound_policy_digest,
        )
