"""Identity bytes must be stable, type-aware and free from infrastructure."""

import json
import os
import subprocess
import sys
from typing import Any

import pytest

from src.canonical import (
    SERIALIZATION_VERSION,
    CanonicalId,
    CanonicalValue,
    CurrencyCode,
    ExactDecimal,
    IdNamespace,
    ReproducibilityConflict,
    ValueState,
    canonical_bytes,
    canonical_sha256,
    deterministic_id,
    sha256_bytes,
)


def test_serialization_version_and_golden_bytes() -> None:
    assert SERIALIZATION_VERSION == 1
    assert canonical_bytes({"b": True, "a": None}) == (
        b'{"contract":"canonical","value":["map",'
        b'[["a",["null"]],["b",["bool",true]]]],"version":1}'
    )
    assert json.loads(canonical_bytes(None))["version"] == 1


def test_maps_ignore_key_order_and_lists_preserve_order() -> None:
    left = {"z": [None, {"b": 2, "a": "ñ"}], "a": False}
    right = {"a": False, "z": [None, {"a": "ñ", "b": 2}]}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert canonical_bytes([1, 2]) != canonical_bytes([2, 1])


def test_unicode_is_utf8_without_lossy_normalization() -> None:
    assert "nómina 😀" in canonical_bytes("nómina 😀").decode("utf-8")
    assert canonical_bytes("é") != canonical_bytes("e\u0301")
    assert canonical_bytes("a\nb") != canonical_bytes("a\\nb")


def test_exact_decimal_normal_form_has_stable_bytes() -> None:
    assert canonical_bytes(ExactDecimal(120, 2)) == canonical_bytes(ExactDecimal(12, 1))
    assert canonical_bytes(ExactDecimal(12, 1)) == (
        b'{"contract":"canonical","value":["decimal","12",1],"version":1}'
    )


def test_canonical_value_preserves_all_semantic_dimensions() -> None:
    base = CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0),
                          currency=CurrencyCode("EUR"))
    equivalent = CanonicalValue(currency=CurrencyCode("EUR"), value=ExactDecimal(0, 9),
                                state=ValueState.PRESENT)
    assert canonical_bytes(base) == canonical_bytes(equivalent)
    variants = [
        base,
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0)),
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0),
                       currency=CurrencyCode("USD")),
        CanonicalValue(state=ValueState.UNKNOWN),
        CanonicalValue(state=ValueState.TECHNICAL_NULL),
        CanonicalValue(state=ValueState.UNRELIABLE, reason_code="source.conflict"),
        CanonicalValue(state=ValueState.UNRELIABLE, reason_code="source.missing"),
    ]
    assert len({canonical_bytes(v) for v in variants}) == len(variants)


def test_type_tags_cannot_be_impersonated_by_user_containers() -> None:
    identifier = deterministic_id("fact", {"line": 1})
    variants: list[Any] = [
        None, "null", False, 0, "0", ExactDecimal(0, 0), [], {},
        ["decimal", "0", 0], {"type": "decimal", "coefficient": 0, "scale": 0},
        CurrencyCode("EUR"), "EUR", identifier, str(identifier),
        ValueState.UNKNOWN, "unknown", IdNamespace.FACT, "fact",
    ]
    assert len({canonical_bytes(v) for v in variants}) == len(variants)


@pytest.mark.parametrize("unsupported", [
    0.0, float("nan"), float("inf"), {"nested": [1.1]}, {1: "key"},
    (1, 2), {1, 2}, b"bytes", object(), "\ud800",
])
def test_serializer_rejects_unsupported_input(unsupported: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_bytes(unsupported)


def test_cycles_fail_but_shared_acyclic_values_are_allowed() -> None:
    cycle: list[Any] = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="[Cc]ycl"):
        canonical_bytes(cycle)
    shared = ["x"]
    assert canonical_bytes([shared, shared]) == canonical_bytes([["x"], ["x"]])


def test_sha256_known_vector_and_canonical_content() -> None:
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert canonical_sha256({"b": 2, "a": 1}) == sha256_bytes(
        canonical_bytes({"a": 1, "b": 2})
    )


@pytest.mark.parametrize("namespace", list(IdNamespace))
def test_deterministic_identifiers_are_valid_explicit_strings(namespace: IdNamespace) -> None:
    identifier = deterministic_id(namespace, {"source": "synthetic", "line": 1})
    assert isinstance(identifier, str)
    assert CanonicalId(str(identifier)) == identifier
    assert identifier.namespace == namespace.value
    assert len(identifier.digest) == 64
    assert str(identifier).startswith(f"{namespace.value}:sha256:")


def test_id_is_domain_separated_and_content_sensitive() -> None:
    first = deterministic_id("fact", {"a": 1, "b": 2})
    assert first == deterministic_id("fact", {"b": 2, "a": 1})
    assert first != deterministic_id("fact", {"a": 2, "b": 2})
    other = deterministic_id("observation", {"a": 1, "b": 2})
    assert first.digest != other.digest


@pytest.mark.parametrize("invalid", [
    "", "fact", "fact:sha256:abc", "FACT:sha256:" + "a" * 64,
    "fact:sha256:" + "A" * 64, "fact:sha256:" + "g" * 64,
    "fact:sha256:" + "a" * 65, " fact:sha256:" + "a" * 64,
])
def test_id_format_is_validated(invalid: str) -> None:
    with pytest.raises(ValueError):
        CanonicalId(invalid)


@pytest.mark.parametrize("namespace", ["", "Fact", "fact:other", "fact ", "a" * 65])
def test_invalid_namespace_is_rejected(namespace: str) -> None:
    with pytest.raises(ValueError):
        deterministic_id(namespace, {})


def test_determinism_across_python_hash_seeds() -> None:
    script = (
        "from src.canonical import deterministic_id; "
        "print(deterministic_id('fact', {k: k for k in {'a', 'b', 'c'}}))"
    )
    outputs = [subprocess.check_output(
        [sys.executable, "-B", "-c", script], text=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    ) for seed in ("1", "72")]
    assert outputs[0] == outputs[1]


def test_reproducibility_conflict_is_a_reusable_contract_error() -> None:
    with pytest.raises(ReproducibilityConflict, match="same identity"):
        raise ReproducibilityConflict("same identity, different content")
