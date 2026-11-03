"""Functional panel visualization and independent visibility over synthetic data."""

from src.income_evolution import project_income
from src.income_view import income_chart
from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page
from tests.unit.test_income_evolution import fixture

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def test_point_chart_has_partial_legend_trace_no_interpolation():
    d, s, g = fixture()
    r = project_income((d,), {d.document_id: s}, {}, [g])
    spec = income_chart(r.rows).to_dict()
    assert spec["spec"]["mark"]["type"] == "point"
    assert "Ordinario identificado (parcial)" in str(spec)
    assert "Fórmula" in str(spec) and "Hecho" in str(spec)
    assert "aggregate" not in str(spec) and "interpolate" not in str(spec)


def test_panel_displays_real_projection_and_independent_control(database, monkeypatch):
    d, s, g = fixture()
    r = project_income((d,), {d.document_id: s}, {}, [g])
    monkeypatch.setattr("src.income_view.load_income", lambda *a, **k: r)
    app = page()
    assert not app.exception
    assert any(x.value == "Evolución retributiva identificada" for x in app.subheader)
    assert "Ordinario identificado (parcial)" in app.multiselect(key="panel_income").value
    inventory = app.metric[0].value
    app.multiselect(key="panel_income").set_value(["Ordinario identificado (parcial)"]).run()
    assert app.metric[0].value == inventory
    assert app.multiselect(key="panel_categories").value
    app.button(key="panel_income_reset").click().run()
    assert len(app.multiselect(key="panel_income").value) == 3


def test_empty_and_error_do_not_create_fake_points(database, monkeypatch):
    from src.canonical_inspection import InspectionError
    from src.income_evolution import IncomeProjection

    monkeypatch.setattr("src.income_view.load_income", lambda *a, **k: IncomeProjection([], ()))
    app = page()
    assert not app.exception
    assert not any(x.key == "panel_income" for x in app.multiselect)

    def fail(*args, **kwargs):
        raise InspectionError("synthetic")

    monkeypatch.setattr("src.income_view.load_income", fail)
    app.run()
    assert not app.exception and any("evolución retributiva" in e.value for e in app.error)


def seed_ordinary(path):
    """Create a complete synthetic canonical pipeline, not a mock chart loader."""
    from src.canonical.documents import (
        DocumentVersion,
        Extraction,
        LogicalDocument,
        document_id,
        extraction_id,
        version_id,
    )
    from src.canonical.evidence import (
        Corpus,
        Person,
        SourceFile,
        corpus_id,
        person_id,
        source_file_id,
    )
    from src.canonical.facts import DocumentaryFact, FactDraft
    from src.canonical.serialization import canonical_sha256
    from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
    from src.economic_mapping import evaluate_direct_totals
    from src.persistence import open_database
    from src.persistence.economics import EconomicRepository
    from tests.unit.test_salary_reconstruction import payroll

    with open_database(path, mode="create") as db:
        repo = EconomicRepository(db.connection)
        person = Person(person_id(), "synthetic")
        corpus = Corpus(corpus_id(), person.person_id, "synthetic", "v1")
        source = SourceFile(source_file_id("a" * 64), "a" * 64, 12, "application/pdf")
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(source)
        for company, month in (
            ("Empresa Uno", 6),
            ("Empresa Uno", 7),
            ("Empresa Uno", 9),
            ("Empresa Dos", 6),
        ):
            key = company + str(month)
            doc = LogicalDocument(
                document_id(corpus.corpus_id, key), corpus.corpus_id, None, "NOMINA_ORDINARIA", key
            )
            version = DocumentVersion(
                version_id(doc.document_id, source.file_id, "whole"),
                doc.document_id,
                source.file_id,
                "whole",
            )
            e = payroll()
            values = {f.fact.fact_key: f.fact.value for f in e.facts}
            values.update(
                {
                    "nomina.empresa": CanonicalValue(state=ValueState.PRESENT, value=company),
                    "nomina.anio": CanonicalValue(
                        state=ValueState.PRESENT, value=ExactDecimal(2025, 0)
                    ),
                    "nomina.mes": CanonicalValue(
                        state=ValueState.PRESENT, value=ExactDecimal(month, 0)
                    ),
                }
            )
            ext = Extraction(
                extraction_id(version.version_id, e.extractor_name, e.extractor_revision, "b" * 64),
                version.version_id,
                e.extractor_name,
                e.extractor_revision,
                "b" * 64,
                canonical_sha256(values),
            )
            repo.register_document(doc)
            repo.register_version(version)
            repo.register_extraction(ext)
            facts = tuple(
                DocumentaryFact.from_draft(ext.extraction_id, FactDraft(k, v))
                for k, v in values.items()
            )
            for f in facts:
                repo.register_fact(f)
            result = evaluate_direct_totals(doc.document_id, facts)
            repo.register_rule(result.rule)
            repo.register_assessment(result.assessment)
            for obs in result.observations:
                repo.register_observation(obs.observation, obs.fact_ids)


def test_native_panel_real_reader_filters_gap_and_navigation(tmp_path, monkeypatch):
    path = tmp_path / "ordinary.sqlite"
    seed_ordinary(path)
    monkeypatch.setenv("ANALISIS_NOMINAS_CANONICAL_DB", str(path))
    before = path.read_bytes()
    app = page()
    assert not app.exception
    assert "Ordinario identificado (parcial)" in app.multiselect(key="panel_income").value
    app.selectbox(key="panel_company").select("Empresa Uno").run()
    app.text_input(key="panel_period").set_value("06/2025 – 09/2025").run()
    assert app.metric[0].value == "3"
    ordinary = [
        r
        for df in app.dataframe
        if "Componente" in df.value
        for r in df.value.to_dict("records")
        if r["Componente"] == "Ordinario identificado (parcial)"
    ]
    assert {r["Fecha"] for r in ordinary} == {"2025-06-01", "2025-07-01", "2025-09-01"}
    assert all("parcial" in r["Cobertura"].lower() for r in ordinary)
    app.multiselect(key="panel_income").set_value(["Ordinario identificado (parcial)"]).run()
    identity = app.session_state["panel_valid_ids"][0]
    app.selectbox(key="panel_document").select(identity).run()
    assert any(
        "Magnitud" in df.value
        and "Ordinario identificado (parcial)" in df.value["Magnitud"].tolist()
        for df in app.dataframe
    )
    app.button(key="panel_back").click().run()
    assert app.multiselect(key="panel_income").value == ["Ordinario identificado (parcial)"]
    assert app.selectbox(key="panel_company").value == "Empresa Uno"
    app.text_input(key="panel_period").set_value("08/2025").run()
    assert any("No hay coincidencias" in x.value for x in app.info)
    assert path.read_bytes() == before and not app.exception
