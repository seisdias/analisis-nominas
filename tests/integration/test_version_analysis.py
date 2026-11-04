"""Real A.3 manifest and documentary points over a synthetic in-memory corpus."""

import json
from dataclasses import replace

import pytest

from src.analytic_dataset import read_analytic_dataset
from src.canonical_inspection import CanonicalInspector
from src.document_concepts import read_document_concepts
from src.economic_components import project_components
from src.version_analysis import analytical_version
from tests.integration.ingestion import test_alten_projection as a3

snapshot = a3.snapshot


class Payroll(a3.SyntheticAlten):
    def prepare(self, data, filename):
        result = super().prepare(data, filename)
        version = result.versions[0].copy()
        payload = json.loads(version["payload"])
        payload["tipo"] = "NOMINA_ORDINARIA"
        payload["conceptos"] = [
            dict(
                codigo=code,
                concepto=label,
                categoria=category,
                columna="devengos",
                importe=10,
                atraso=False,
            )
            for code, label, category in [
                ("9122", "Bono", "bono"),
                ("9122", "Bono", "bono"),
                ("9016", "P.P. Extra Verano", "paga_extra_incluida"),
            ]
        ]
        version["payload"] = json.dumps(payload)
        period = dict(result.periods[0], tipo="NOMINA_ORDINARIA")
        period["period_key"] = period["period_key"].replace("nomina_ordinaria", "NOMINA_ORDINARIA")
        version["period_key"] = period["period_key"]
        return replace(result, periods=(period,), versions=(version,))


def setup(snapshot, count=2, resolve=True):
    repo, conn, bindings, _ = snapshot
    run, sources, _ = a3.prepare(snapshot, count, Payroll())
    choice = a3.resolution_for(repo, conn)
    a3.finalize_alten(conn, run.run_id, bindings, sources, (choice,) if resolve else ())
    inspector = CanonicalInspector(conn)
    (doc,) = read_analytic_dataset(inspector)
    return doc, read_document_concepts(inspector, doc.document_id), choice


@pytest.mark.parametrize("count", [2, 3])
def test_only_authorized_occurrences_enter_series(snapshot, count):
    d, s, choice = setup(snapshot, count)
    result = analytical_version(s)
    assert result.extraction and result.extraction.version_id == choice.version_id
    points = project_components((d,), {d.document_id: s}, {}).points
    assert len(points) == 3
    assert {p.occurrence.version_id for p in points} == {choice.version_id}
    assert len({p.amount.fact.fact_id for p in points}) == 3
    assert not project_components(
        (d,), {d.document_id: s}, {d.document_id: "Restricción local"}
    ).points


def test_without_manifest_inspection_cannot_select(snapshot):
    d, s, _ = setup(snapshot, resolve=False)
    assert analytical_version(s).extraction is None
    assert not project_components((d,), {d.document_id: s}, {}).points


@pytest.mark.parametrize(
    "mutation",
    [
        "inventory",
        "projection_hash",
        "source_hash",
        "projection_id",
        "pages",
        "multiple",
        "mixed",
        "truncated",
    ],
)
def test_invalid_provenance_fails_closed(snapshot, mutation):
    d, s, choice = setup(snapshot)
    es = list(s.extractions)
    pi = next(i for i, e in enumerate(es) if e.extractor_name == "alten-economic-projection")
    si = next(i for i, e in enumerate(es) if e.version_id == choice.version_id and e.concepts)
    if mutation == "inventory":
        s = replace(s, version_ids=s.version_ids + ("unknown",))
    if mutation == "projection_hash":
        es[pi] = replace(es[pi], content_hash="wrong")
    if mutation == "source_hash":
        es[si] = replace(es[si], content_hash="wrong")
    if mutation == "projection_id":
        es[pi] = replace(es[pi], extraction_id="wrong")
    if mutation == "multiple":
        es.append(es[pi])
    if mutation == "mixed":
        es[si] = replace(es[si], version_id="other")
    if mutation == "pages":
        es[si] = replace(es[si], facts=tuple(replace(f, pages=()) for f in es[si].facts))
    if mutation == "truncated":
        es[si] = replace(es[si], concepts=es[si].concepts[:-1])
    bad = replace(s, extractions=tuple(es))
    assert analytical_version(bad).extraction is None
    assert not project_components((d,), {d.document_id: bad}, {}).points


def test_foreign_total_support_blocks_components(snapshot):
    d, s, _ = setup(snapshot)
    invalid = replace(
        d, observation_facts=tuple((oid, ("foreign",)) for oid, _ in d.observation_facts)
    )
    assert not project_components((invalid,), {d.document_id: s}, {}).points


def test_comparison_and_inspection_do_not_change_series(snapshot, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from src.income_evolution import project_income

    d, s, choice = setup(snapshot, 3)
    monkeypatch.setattr("src.concepts_view.load_document_concepts", lambda *args: s)
    app = AppTest.from_string(
        "from pathlib import Path\nfrom src.concepts_view import render_concepts\nrender_concepts(Path('synthetic'),'doc')"
    ).run()
    assert not app.exception
    assert any("Comparación de versiones" == h.value for h in app.subheader)
    assert app.selectbox[0].value is None
    other = next(v for v in s.version_ids if v != choice.version_id)
    app.selectbox[0].select(other).run()
    assert not app.exception
    assert any("Solo inspección" in c.value for c in app.caption)
    income = project_income((d,), {d.document_id: s}, {}, [])
    assert len(income.rows) == 3 and {r["Versión"] for r in income.rows} == {choice.version_id}


def test_comparison_preserves_extraction_reconstruction_and_certification(snapshot):
    from src.canonical.certification import CertificationRequirements
    from src.salary_reconstruction import reconstruct

    d, s, _ = setup(snapshot)
    inspector = CanonicalInspector(snapshot[1])
    before = [
        inspector.explain(o.observation_id, CertificationRequirements())["certification"]
        for o in d.observations
    ]
    for e in s.extractions:
        result = reconstruct(e)
        assert (
            result.scope.version_id == e.version_id
            and result.scope.extraction_id == e.extraction_id
        )
        assert all(p.source.source.version_id == e.version_id for p in result.parts)
    assert analytical_version(s).extraction is not None
    assert all(c["status"] == "certified" for c in before)
    assert before == [
        inspector.explain(o.observation_id, CertificationRequirements())["certification"]
        for o in d.observations
    ]


def test_snapshot_missing_projection_or_alternative_rejected(snapshot):
    d, s, choice = setup(snapshot)
    for v in d.provenance:
        changed = replace(
            d,
            provenance=tuple(replace(p, extraction_ids=()) if p == v else p for p in d.provenance),
        )
        assert not project_components((changed,), {d.document_id: s}, {}).points
