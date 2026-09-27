"""Versioned, type-tagged UTF-8 identity bytes; no floats or repr fallbacks."""

import hashlib
import json

from src.canonical.identifiers import CanonicalId, IdNamespace, validate_namespace
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState

SERIALIZATION_VERSION = 1


def _encode(value: object, ancestors: set[int]) -> list[object]:
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if type(value) is int:
        return ["int", str(value)]
    if type(value) is str:
        return ["str", value]
    if type(value) is ExactDecimal:
        return ["decimal", str(value.coefficient), value.scale]
    if type(value) is CurrencyCode:
        return ["currency", value.code]
    if type(value) is CanonicalId:
        return ["id", str(value)]
    if type(value) is ValueState:
        return ["value_state", value.value]
    if type(value) is IdNamespace:
        return ["id_namespace", value.value]
    if type(value) is CanonicalValue:
        return ["canonical_value", _encode({
            "state": value.state, "value": value.value,
            "currency": value.currency, "reason_code": value.reason_code,
        }, ancestors)]
    if type(value) not in (list, dict):
        raise TypeError("Unsupported canonical type; floats and implicit conversions are forbidden")
    identity = id(value)
    if identity in ancestors:
        raise ValueError("Cyclic canonical input")
    ancestors.add(identity)
    try:
        if isinstance(value, list):
            return ["list", [_encode(item, ancestors) for item in value]]
        assert isinstance(value, dict)
        if any(type(key) is not str for key in value):
            raise TypeError("Canonical map keys must be plain strings")
        return ["map", [[key, _encode(value[key], ancestors)] for key in sorted(value)]]
    finally:
        ancestors.remove(identity)


def canonical_bytes(value: object) -> bytes:
    """Serialize the closed set of supported values as a v1 tagged JSON tree.

    Maps sort plain string keys by Unicode code point; lists preserve order.
    Unicode is preserved, not normalized. Integers use decimal text inside their
    tag to avoid consumer precision loss. User containers cannot impersonate tags.
    Unsupported values (including all floats), cycles and invalid Unicode fail.
    """
    envelope = {"contract": "canonical", "version": SERIALIZATION_VERSION,
                "value": _encode(value, set())}
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Hash supplied bytes only; never opens a file."""
    if type(value) is not bytes:
        raise TypeError("SHA256 input must be bytes")
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def deterministic_id(namespace: str, content: object) -> CanonicalId:
    """Include namespace in both the identifier and its hash preimage."""
    validate_namespace(namespace)
    digest = canonical_sha256({"namespace": str(namespace), "content": content})
    return CanonicalId(f"{namespace}:sha256:{digest}")
