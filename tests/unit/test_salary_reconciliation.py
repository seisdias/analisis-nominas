"""Exact diagnostic arithmetic requires an explicit reviewed coverage contract."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from src.salary_reconciliation import ReconciliationContract, Status, reconcile
from tests.unit.test_document_concepts import fact, project


def source(gross=10000, ded=2000, net=8000):
    fs = []
    for n, (column, value) in enumerate([("devengos", 10000), ("deducciones", 2000)]):
        fs += [
            fact(f"payload/conceptos/{n}/columna", column),
            fact(f"payload/conceptos/{n}/importe", value),
        ]
    fs += [
        fact("payload/total_devengado", gross),
        fact("payload/total_deducir", ded),
        fact("payload/liquido_percibir", net),
    ]
    return replace(project(fs), extractor_name="synthetic", extractor_revision="1")


def contract(**changes):
    c = ReconciliationContract(
        "synthetic",
        "1",
        "Synthetic complete-table/sign contract; not enabled for private data",
        True,
        True,
        True,
        True,
        same_unit=True,
    )
    return replace(c, **changes)


def test_equal_numbers_without_completeness_never_reconcile():
    r = reconcile(source())
    assert all(d.status == Status.INCOMPLETE for d in r)
    assert all(d.difference is None for d in r)


def test_complete_earnings_deductions_and_net_exact():
    e = source()
    r = reconcile(e, contract())
    assert all(d.status == Status.RECONCILED and d.difference == Decimal(0) for d in r)
    assert all(d.extraction_id == e.extraction_id and d.version_id == e.version_id for d in r)
    assert r[0].participants and r[0].formula
    assert all(d.knowledge.value == "Calculado" for d in r)


def test_difference_is_unexplained_not_bonus():
    r = reconcile(source(gross=10001), contract())
    assert r[0].status == Status.DIFFERENCE and r[0].difference == Decimal("-0.01")
    assert "Diferencia no explicada" in r[0].reason


@pytest.mark.parametrize(
    "change",
    [
        "incomplete",
        "signs",
        "revision",
        "missing_total",
        "mixed_alias",
        "unknown_amount",
        "unreliable",
        "no_concepts",
    ],
)
def test_exclusions(change):
    from src.canonical.values import ValueState

    e = source()
    c = contract()
    if change == "incomplete":
        c = contract(earnings_complete=False)
    if change == "signs":
        c = contract(signed_columns=False)
    if change == "revision":
        c = contract(extractor_revision="other")
    if change == "missing_total":
        e = replace(
            e, facts=tuple(f for f in e.facts if f.fact.fact_key != "payload/total_devengado")
        )
    if change == "mixed_alias":
        other = project([fact("nomina.total_devengado", 10000)]).facts[0]
        e = replace(e, facts=e.facts + (other,))
    if change in ("unknown_amount", "unreliable"):
        state = ValueState.UNKNOWN if change == "unknown_amount" else ValueState.UNRELIABLE
        concepts = list(e.concepts)
        first = concepts[0]
        a = first.get("importe")
        altered = replace(a, fact=fact(a.fact.fact_key, None, state=state))
        concepts[0] = replace(
            first,
            attributes=tuple((k, altered if k == "importe" else v) for k, v in first.attributes),
        )
        e = replace(e, concepts=tuple(concepts))
    if change == "no_concepts":
        e = replace(e, concepts=())
    assert reconcile(e, c)[0].status != Status.RECONCILED


def test_context_precision_cannot_round_diagnostic():
    with localcontext() as ctx:
        ctx.prec = 2
        r = reconcile(source(gross=10001), contract())
    assert r[0].difference == Decimal("-0.01")


def test_scalars_not_added_to_rows_and_deterministic():
    e = source()
    extra = project([fact("payload/salario_base", 10000)]).facts
    assert reconcile(replace(e, facts=e.facts + extra), contract()) == reconcile(e, contract())
    assert reconcile(replace(e, concepts=tuple(reversed(e.concepts))), contract()) == reconcile(
        e, contract()
    )


def test_signed_negative_components_are_exact_and_never_relabelled():
    fs = []
    for n, (column, amount) in enumerate([("devengos", -1000), ("deducciones", -200)]):
        fs.extend(
            [
                fact(f"payload/conceptos/{n}/columna", column),
                fact(f"payload/conceptos/{n}/importe", amount),
            ]
        )
    fs.extend(
        [
            fact("payload/total_devengado", -1000),
            fact("payload/total_deducir", -200),
            fact("payload/liquido_percibir", -800),
        ]
    )
    e = replace(project(fs), extractor_name="synthetic", extractor_revision="1")
    assert all(d.status == Status.RECONCILED for d in reconcile(e, contract()))
    assert all(d.status == Status.UNAVAILABLE for d in reconcile(e, contract(signed_columns=False)))


@pytest.mark.parametrize(
    "case",
    [
        "unknown_unit",
        "mixed_currency",
        "missing_net_contract",
        "foreign_version",
        "duplicate_occurrence",
        "no_evidence_reference",
    ],
)
def test_additional_uncertainty_is_not_a_numeric_residue(case):
    from src.canonical.values import CurrencyCode

    e = source()
    c = contract()
    if case == "unknown_unit":
        c = contract(same_unit=False)
    if case == "missing_net_contract":
        c = contract(net_relation=False)
    if case == "no_evidence_reference":
        c = contract(evidence_reference="")
    if case == "foreign_version":
        e = replace(e, concepts=(replace(e.concepts[0], version_id="other"), *e.concepts[1:]))
    if case == "duplicate_occurrence":
        e = replace(e, concepts=e.concepts + e.concepts[:1])
    if case == "mixed_currency":
        target = next(f for f in e.facts if f.fact.fact_key == "payload/liquido_percibir")
        replacement = replace(
            target,
            fact=replace(
                target.fact, value=replace(target.fact.value, currency=CurrencyCode("USD"))
            ),
        )
        e = replace(e, facts=tuple(replacement if f == target else f for f in e.facts))
    assert reconcile(e, c)[2].difference is None


def test_independent_versions_and_extractions_never_share_totals():
    from src.document_concepts import project_extraction
    from tests.unit.test_document_concepts import DOC, EXT

    first = source()
    fs = [fact(f.fact.fact_key, f.fact.value.value, ext=EXT) for f in first.facts]
    second = replace(
        project_extraction(DOC, "version-two", EXT, fs),
        extractor_name="synthetic",
        extractor_revision="1",
    )
    assert {d.version_id for d in reconcile(first, contract())} == {first.version_id}
    assert {d.version_id for d in reconcile(second, contract())} == {"version-two"}
    without_totals = replace(
        second, facts=tuple(f for f in second.facts if "/conceptos/" in f.fact.fact_key)
    )
    assert all(d.difference is None for d in reconcile(without_totals, contract()))


def test_informational_rows_and_repeated_codes_are_not_duplicate_payments():
    e = source()
    extra = project(
        [fact("payload/conceptos/3/columna", "bases"), fact("payload/conceptos/3/importe", 99999)]
    )
    enriched = replace(e, concepts=e.concepts + extra.concepts, facts=e.facts + extra.facts)
    assert all(d.status == Status.RECONCILED for d in reconcile(enriched, contract()))


def test_truncated_projection_cannot_claim_a_complete_extraction():
    e = source()
    truncated = replace(e, concepts=e.concepts[:1])
    assert all(
        d.status == Status.CONFLICT and d.difference is None
        for d in reconcile(truncated, contract())
    )
