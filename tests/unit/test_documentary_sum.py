"""Exploratory arithmetic never promotes canonical eligibility."""

from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from src.analytic_dataset import VersionProvenance
from src.annual_summary import annual_summary
from src.canonical.values import CurrencyCode, ExactDecimal
from src.documentary_sum import exploratory_sum
from tests.unit.test_documentary_coverage import document


def example(*, amounts=(12345, 6789), currency="EUR"):
    records = tuple(document(str(i), month=i + 1) for i in range(len(amounts)))
    records = tuple(
        replace(
            r,
            document=replace(
                r.document, provenance=(VersionProvenance("v" + str(i), "f", "a" * 64, (), ("e",)),)
            ),
        )
        for i, r in enumerate(records)
    )
    group = annual_summary(records, {}, {}, [], years=(2025, 2025)).groups[0]
    rows = [
        dict(
            document_id=str(i),
            series=series,
            observation_id=f"{i}-{series}",
            document_status="certified",
            source_version_ids=(r.document.provenance[0].version_id,),
            eligibility="evidence_only",
            value=dict(
                status="certified",
                amount=ExactDecimal(a, 2),
                currency=CurrencyCode(currency) if currency else None,
            ),
        )
        for i, (r, a) in enumerate(zip(records, amounts))
        for series in ("Bruto", "Neto")
    ]
    return group, rows


def calculate(group, rows, series="Bruto", **kwargs):
    return exploratory_sum(
        group, rows, series, document_relations=(), observation_relations=(), **kwargs
    )


def test_partial_year_exact_sum_no_components_or_annual_authority():
    g, rows = example()
    r = calculate(g, rows)
    assert r.amount == Decimal("191.34") and r.status == "calculable"
    assert len(r.included) == 2 and r.months == (1, 2)
    assert g.aggregate is None and all(o["eligibility"] == "evidence_only" for o in rows)
    assert calculate(g, rows + rows).amount == r.amount


@pytest.mark.parametrize(
    "case", ["currency", "mixed", "unknown", "unreliable", "restricted", "multi", "duplicate"]
)
def test_blockers_never_manufacture_zero(case):
    g, rows = example()
    if case == "currency":
        for row in rows:
            row["value"]["currency"] = None
    elif case == "mixed":
        rows[2]["value"]["currency"] = CurrencyCode("USD")
    elif case in ("unknown", "unreliable"):
        for row in rows:
            row["value"]["status"] = case
            row["value"]["amount"] = None
    elif case == "restricted":
        g = replace(
            g, documents=tuple(replace(d, exclusion="Restricción C.3") for d in g.documents)
        )
    elif case == "multi":
        g = replace(
            g,
            documents=tuple(
                replace(
                    d,
                    record=replace(
                        d.record,
                        document=replace(
                            d.record.document, provenance=d.record.document.provenance * 2
                        ),
                    ),
                )
                for d in g.documents
            ),
        )
    else:
        rows[2]["observation_id"] = rows[0]["observation_id"]
    r = calculate(g, rows)
    assert r.status == "blocked" and r.amount is None and len(r.excluded) == 2


def test_gross_and_net_independent_partial_and_empty():
    g, rows = example()
    rows[1]["value"]["amount"] = None
    assert calculate(g, rows).status == "calculable"
    net = calculate(g, rows, "Neto")
    assert net.status == "partial" and net.amount == Decimal("67.89")
    assert len(net.excluded) == 1
    assert calculate(replace(g, documents=()), rows).status == "empty"


@pytest.mark.parametrize("amounts", [(0, -123), (10**16, 1)])
def test_zero_negative_and_decimal_precision(amounts):
    g, rows = example(amounts=amounts)
    with localcontext() as ctx:
        ctx.prec = 6
        r = calculate(g, rows)
    assert r.amount == ExactDecimal(sum(amounts), 2).to_decimal()


def test_explicit_relation_blocks_even_with_other_endpoint_outside_selection():
    g, rows = example()
    relation = ("0", "outside", "duplicate_of")
    r = exploratory_sum(g, rows, "Bruto", document_relations=(relation,), observation_relations=())
    assert r.status == "partial" and r.included == ("1",)


def test_authorized_version_uses_only_matching_support():
    g, rows = example()
    first = g.documents[0]
    provenance = first.record.document.provenance
    alternate = replace(provenance[0], version_id="alternate")
    first = replace(
        first,
        version_id=provenance[0].version_id,
        record=replace(
            first.record,
            document=replace(first.record.document, provenance=provenance + (alternate,)),
        ),
    )
    g = replace(g, documents=(first, g.documents[1]))
    assert calculate(g, rows).status == "calculable"
    rows[0]["source_version_ids"] = ("alternate",)
    assert calculate(g, rows).included == ("1",)


def test_extra_and_integrated_components_are_not_extra_arithmetic_inputs():
    from src.analytic_dataset import DocumentCategory
    from src.salary_reconstruction import Bucket, reconstruct
    from tests.unit.test_income_evolution import fixture

    g, rows = example()
    first, extra = g.documents
    extra = replace(
        extra,
        record=replace(
            extra.record, document=replace(extra.record.document, category=DocumentCategory.EXTRA)
        ),
    )
    _, source, _ = fixture()
    part = reconstruct(source.extractions[0]).parts[0]
    first = replace(
        first,
        component_parts=tuple(
            replace(part, bucket=b) for b in (Bucket.VARIABLE, Bucket.PRORATION, Bucket.EXTRA)
        ),
    )
    assert calculate(replace(g, documents=(first, extra)), rows).amount == Decimal("191.34")


def test_observation_relations_and_explicit_exclusion_are_independent_by_magnitude():
    g, rows = example()
    result = exploratory_sum(
        g,
        rows,
        "Bruto",
        document_relations=(),
        observation_relations=(("0-Bruto", "other", "contained_in"),),
    )
    assert result.included == ("1",)
    rows[0]["eligibility"] = "excluded"
    assert calculate(g, rows).included == ("1",)
    assert calculate(g, rows, "Neto").status == "calculable"


def test_no_amount_coincidence_or_document_repetition_infers_duplicate_payment():
    g, rows = example(amounts=(100, 100))
    g = replace(g, documents=g.documents + g.documents)
    assert calculate(g, rows).amount == Decimal("2")
    assert calculate(g, rows).included == ("0", "1")
