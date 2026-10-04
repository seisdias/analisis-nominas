"""Infrastructure-free canonical values: exactness and explicit absence."""

from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from typing import Any

import pytest

from src.canonical import CanonicalValue, CurrencyCode, ExactDecimal, ValueState


@pytest.mark.parametrize(("coefficient", "scale", "expected"), [
    (0, 9, (0, 0)), (120, 2, (12, 1)), (-20153, 2, (-20153, 2)),
    (1, 9, (1, 9)), (2**63 - 1, 0, (2**63 - 1, 0)),
    (-2**63, 0, (-2**63, 0)),
])
def test_exact_decimal_normal_form(coefficient: int, scale: int,
                                   expected: tuple[int, int]) -> None:
    value = ExactDecimal(coefficient, scale)
    assert (value.coefficient, value.scale) == expected


def test_decimal_equality_is_numeric_without_rounding() -> None:
    assert ExactDecimal(120, 2) == ExactDecimal(12, 1)
    assert ExactDecimal(120, 2) != ExactDecimal(121, 2)
    assert len({ExactDecimal(120, 2), ExactDecimal(12, 1)}) == 1
    assert ExactDecimal(0, 9) == ExactDecimal(0, 0)


@pytest.mark.parametrize(("coefficient", "scale"), [
    (1, -1), (1, 10), (1, True), (True, 0), (1.0, 0), (1, 1.0),
    ("1", 0), (2**63, 0), (-2**63 - 1, 0),
])
def test_decimal_rejects_invalid_representation(coefficient: Any, scale: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        ExactDecimal(coefficient, scale)


def test_coefficient_limit_applies_after_exact_normalization() -> None:
    assert ExactDecimal((2**63 - 1) * 10, 1) == ExactDecimal(2**63 - 1, 0)


@pytest.mark.parametrize(("text", "expected"), [
    ("0", ExactDecimal(0, 0)), ("-0.00", ExactDecimal(0, 0)),
    ("+001.20", ExactDecimal(12, 1)), ("-201.53", ExactDecimal(-20153, 2)),
    ("0.000000001", ExactDecimal(1, 9)),
    ("1.2000000000", ExactDecimal(12, 1)),
])
def test_decimal_from_text(text: str, expected: ExactDecimal) -> None:
    assert ExactDecimal.from_text(text) == expected


def test_decimal_separator_is_explicit() -> None:
    assert ExactDecimal.from_text("-201,53", decimal_separator=",") == ExactDecimal(-20153, 2)
    with pytest.raises(ValueError):
        ExactDecimal.from_text("-201,53")
    with pytest.raises(ValueError):
        ExactDecimal.from_text("1", decimal_separator=";")


@pytest.mark.parametrize("text", [
    "", " 1", "1 ", "1_000", "1,000.00", "1.000,00", "1e2", ".5", "1.",
    "NaN", "Infinity", "１.２", "0.0000000001", "9223372036854775808",
])
def test_ambiguous_or_unrepresentable_text_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        ExactDecimal.from_text(text)


@pytest.mark.parametrize("text", ["0", "-201.53", "1.2300", "1E+3", "0.000000001"])
def test_decimal_conversion_is_exact_under_small_context(text: str) -> None:
    original = Decimal(text)
    with localcontext() as context:
        context.prec = 1
        value = ExactDecimal.from_decimal(original)
        assert value.to_decimal() == original


@pytest.mark.parametrize("text", [
    "NaN", "sNaN", "Infinity", "-Infinity", "1E-10", "1E+1000000",
    "-9223372036854775809",
])
def test_decimal_never_silently_rounds(text: str) -> None:
    with pytest.raises(ValueError):
        ExactDecimal.from_decimal(Decimal(text))


def test_zero_with_extreme_exponent_is_still_exact_zero() -> None:
    assert ExactDecimal.from_decimal(Decimal("-0E-1000000")) == ExactDecimal(0, 0)


@pytest.mark.parametrize("invalid", [0.1, 1, "1"])
def test_from_decimal_requires_decimal(invalid: Any) -> None:
    with pytest.raises(TypeError):
        ExactDecimal.from_decimal(invalid)


@pytest.mark.parametrize("code", ["EUR", "USD", "XTS"])
def test_currency_format_without_hardcoded_registry(code: str) -> None:
    assert CurrencyCode(code).code == code


@pytest.mark.parametrize("code", ["eur", "EU", "EURO", " EU", "E1R", "ÉUR", ""])
def test_invalid_currency_is_rejected(code: str) -> None:
    with pytest.raises(ValueError):
        CurrencyCode(code)


def test_zero_and_negative_money_are_present() -> None:
    for amount in (ExactDecimal(0, 0), ExactDecimal(-20153, 2)):
        value = CanonicalValue(state=ValueState.PRESENT, value=amount, currency=CurrencyCode("EUR"))
        assert value.value == amount
        assert value.currency == CurrencyCode("EUR")


@pytest.mark.parametrize("state", [
    ValueState.TECHNICAL_NULL, ValueState.NOT_EXTRACTED, ValueState.NOT_PRESENT,
    ValueState.UNKNOWN,
])
def test_absence_is_explicit_and_does_not_invent_currency(state: ValueState) -> None:
    value = CanonicalValue(state=state)
    assert value.value is None
    assert value.currency is None


@pytest.mark.parametrize("state", [s for s in ValueState if s not in {
    ValueState.PRESENT, ValueState.UNRELIABLE,
}])
def test_absence_rejects_even_zero_candidate(state: ValueState) -> None:
    with pytest.raises(ValueError):
        CanonicalValue(state=state, value=ExactDecimal(0, 0), reason_code="source.absent")


def test_present_requires_a_value() -> None:
    with pytest.raises(ValueError):
        CanonicalValue(state=ValueState.PRESENT)


@pytest.mark.parametrize("state", [ValueState.NOT_APPLICABLE, ValueState.UNRELIABLE])
def test_explained_states_require_reason(state: ValueState) -> None:
    with pytest.raises(ValueError):
        CanonicalValue(state=state)
    assert CanonicalValue(state=state, reason_code="source.unsupported").value is None


def test_unreliable_monetary_candidate_is_preserved() -> None:
    value = CanonicalValue(state=ValueState.UNRELIABLE, value=ExactDecimal(123, 2),
                           currency=CurrencyCode("EUR"), reason_code="source.conflict")
    assert value.value == ExactDecimal(123, 2)


def test_text_present_and_unknown_currency() -> None:
    assert CanonicalValue(state=ValueState.PRESENT, value="nómina").value == "nómina"
    assert CanonicalValue(state=ValueState.PRESENT, value="").value == ""
    assert CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(1, 0)).currency is None
    assert CanonicalValue(state=ValueState.UNKNOWN, currency=CurrencyCode("EUR")).value is None


@pytest.mark.parametrize("fields", [
    {"state": "present", "value": "text"},
    {"state": ValueState.PRESENT, "value": 1.5},
    {"state": ValueState.PRESENT, "value": True},
    {"state": ValueState.PRESENT, "value": Decimal("1")},
    {"state": ValueState.PRESENT, "value": "text", "currency": CurrencyCode("EUR")},
    {"state": ValueState.UNKNOWN, "currency": "EUR"},
    {"state": ValueState.UNKNOWN, "reason_code": ""},
    {"state": ValueState.UNKNOWN, "reason_code": "free text"},
])
def test_contradictory_or_untyped_values_fail(fields: dict[str, Any]) -> None:
    with pytest.raises((TypeError, ValueError)):
        CanonicalValue(**fields)


@pytest.mark.parametrize(("instance", "field", "replacement"), [
    (ExactDecimal(1, 0), "coefficient", 2),
    (CurrencyCode("EUR"), "code", "USD"),
    (CanonicalValue(state=ValueState.UNKNOWN), "state", ValueState.PRESENT),
])
def test_value_objects_are_immutable(instance: Any, field: str, replacement: Any) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field, replacement)
