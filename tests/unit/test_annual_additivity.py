"""Reject demonstrable impediments without inventing an annual authorization."""

from dataclasses import replace

import pytest

from src.annual_summary import Additivity, annual_summary
from src.canonical.economics import EconomicObservation, observation_id
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from tests.unit.test_documentary_coverage import document


def record(identity, *, currency=None, eligibility="evidence_only", magnitude="documentary_gross"):
    key = identity + magnitude
    assessment = "assessment:sha256:" + "a" * 64
    obs = EconomicObservation(
        observation_id=observation_id(assessment, key),
        assessment_id=assessment,
        observation_key=key,
        magnitude=magnitude,
        value=CanonicalValue(
            state=ValueState.PRESENT,
            value=ExactDecimal(123456, 2),
            currency=CurrencyCode(currency) if currency else None,
        ),
        eligibility=eligibility,
        economic_status="usable",
    )
    r = document(identity)
    return replace(r, document=replace(r.document, observations=(obs,)))


def group(*records):
    return annual_summary(records, {}, {}, [], years=(2025, 2025)).groups[0]


@pytest.mark.parametrize("currency", [None, "EUR"])
def test_known_or_unknown_currency_is_not_an_annual_contract(currency):
    result = group(record("a", currency=currency), record("b", currency=currency))
    assert result.additivity == Additivity.UNACCREDITED
    assert result.aggregate is None


def test_incompatible_explicit_currencies_reject_same_magnitude_universe():
    result = group(record("a", currency="EUR"), record("b", currency="USD"))
    assert result.additivity == Additivity.REJECTED
    assert result.aggregate is None and "monedas" in result.reason


def test_missing_currency_is_uncertainty_not_incompatibility():
    assert group(record("a", currency="EUR"), record("b")).additivity == Additivity.UNACCREDITED


def test_excluded_observation_rejects_its_inclusion_not_other_documents():
    excluded = record("a", eligibility="excluded")
    good = record("b", eligibility="candidate")
    assert group(excluded, good).additivity == Additivity.REJECTED
    assert group(good).additivity == Additivity.UNACCREDITED


def test_same_observation_cannot_be_counted_as_two_logical_documents():
    a = record("a")
    b = record("b")
    b = replace(b, document=replace(b.document, observations=a.document.observations))
    result = group(a, b)
    assert result.additivity == Additivity.REJECTED and "observación" in result.reason
    assert len(result.documents) == 2  # inventory remains inspectable


def test_equal_values_with_distinct_identity_do_not_prove_duplication():
    assert group(record("a"), record("b")).additivity == Additivity.UNACCREDITED


def test_representation_hold_is_not_an_economic_nonadditivity_decision():
    a = replace(record("a"), presentation_restricted=True)
    assert group(a).additivity == Additivity.UNACCREDITED


def test_gross_and_net_units_are_not_compared_as_one_magnitude():
    result = group(
        record("a", currency="EUR"), record("b", currency="USD", magnitude="documentary_net")
    )
    assert result.additivity == Additivity.UNACCREDITED
    assert result.aggregate is None
