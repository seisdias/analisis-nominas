"""Currency must be scoped to the certified amount, not inferred from payroll context."""

from dataclasses import replace

import pytest

from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.documentary_currency import INSIS_REVISION, attest_net


def attest(text="LIQUIDO TOTAL A PERCIBIR (A-B) EUROS 1.234,56", **kwargs):
    values = dict(
        document_id="doc",
        version_id="version",
        extraction_id="extraction",
        observation_id="obs",
        fact_id="fact",
        file_sha256="a" * 64,
        parser="InsisParser",
        revision=INSIS_REVISION,
        page=1,
        value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(123456, 2)),
        text=text,
    )
    values.update(kwargs)
    return attest_net(**values)


def test_explicit_net_currency_preserves_trace_and_exact_amount():
    e = attest()
    assert e is not None and e.currency.code == "EUR"
    assert e.amount == ExactDecimal(123456, 2)
    assert (e.document_id, e.version_id, e.extraction_id, e.fact_id, e.page) == (
        "doc",
        "version",
        "extraction",
        "fact",
        1,
    )
    assert e.scope == "documentary_net" and e.file_sha256 == "a" * 64
    assert e.text_sha256 and e.contract


@pytest.mark.parametrize(
    "text",
    [
        "IMPORTE EN EUROS 1.234,56",
        "TODOS LOS IMPORTES EN EUROS\nLIQUIDO TOTAL A PERCIBIR (A-B) 1.234,56",
        "BASE EN EUROS 1.234,56\nLIQUIDO TOTAL A PERCIBIR (A-B) 1.234,56",
        "LIQUIDO TOTAL A PERCIBIR (A-B) 205415 PTA 1.234,56",
        "LIQUIDO TOTAL A PERCIBIR (A-B) EUROS 1.234,57",
        "LIQUIDO TOTAL A PERCIBIR (A-B) EUROS 1.234,56\nMONEDA USD",
        "LIQUIDO TOTAL A PERCIBIR (A-B) EUROS 1.234,56\nLIQUIDO TOTAL A PERCIBIR (A-B) EUROS 1.234,56",
    ],
)
def test_missing_wrong_scope_conflicting_or_ambiguous_evidence_rejected(text):
    assert attest(text) is None


@pytest.mark.parametrize("state", [ValueState.UNKNOWN, ValueState.UNRELIABLE])
def test_nonusable_fact_cannot_gain_currency_authority(state):
    assert attest(value=CanonicalValue(state=state, reason_code="test.absent")) is None


def test_unreviewed_extractor_cannot_use_contract():
    assert attest(parser="OtherParser") is None
    assert attest(revision="other") is None


def test_evidence_is_specific_to_observation_version_and_magnitude():
    from src.documentary_sum import exploratory_sum
    from tests.unit.test_documentary_sum import example

    g, rows = example(amounts=(123456,), currency=None)
    net = rows[1]
    e = attest(
        document_id="0",
        version_id=net["source_version_ids"][0],
        observation_id=net["observation_id"],
    )
    net["currency_evidence"] = e

    def calculate(series):
        return exploratory_sum(g, rows, series, document_relations=(), observation_relations=())

    assert calculate("Neto").status == "calculable"
    assert calculate("Bruto").status == "blocked"
    net["currency_evidence"] = replace(e, version_id="alternative")
    assert calculate("Neto").status == "blocked"
    net["currency_evidence"] = replace(e, observation_id="other")
    assert calculate("Neto").status == "blocked"


def test_canonical_conflict_restriction_and_partial_selection_still_block():
    from src.canonical.values import CurrencyCode
    from src.documentary_sum import exploratory_sum
    from tests.unit.test_documentary_sum import example

    g, rows = example(amounts=(123456, 100), currency=None)
    rows[1]["currency_evidence"] = attest(
        document_id="0", version_id=rows[1]["source_version_ids"][0], observation_id="0-Neto"
    )

    def calculate(group=g):
        return exploratory_sum(group, rows, "Neto", document_relations=(), observation_relations=())

    assert calculate().status == "partial"
    assert calculate().currency_evidence[0].fact_id == "fact"
    rows[1]["value"]["currency"] = CurrencyCode("USD")
    assert calculate().status == "blocked"
    rows[1]["value"]["currency"] = None
    restricted = replace(
        g, documents=tuple(replace(d, exclusion="Coritel: restricción local") for d in g.documents)
    )
    assert calculate(restricted).status == "blocked"


def test_unreliable_value_retaining_number_cannot_gain_currency():
    assert (
        attest(
            value=CanonicalValue(
                state=ValueState.UNRELIABLE,
                value=ExactDecimal(123456, 2),
                reason_code="test.unreliable",
            )
        )
        is None
    )
