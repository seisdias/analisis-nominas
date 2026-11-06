"""Evidence limits visible in both existing entry points, without changing context."""

from src.income_evolution import project_income
from tests.integration.test_analysis_panel import page
from tests.integration.test_income_view import isolated_configuration, seed_ordinary  # noqa: F401
from tests.unit.test_income_evolution import fixture


def test_projection_has_requirements_before_series_visibility():
    d, s, g = fixture()
    result = project_income((d,), {d.document_id: s}, {}, [g])
    assert d.document_id in result.salary_evidence
    report = result.salary_evidence[d.document_id]
    assert report.ordinary.amount is not None
    assert not next(c for c in report.requirements if c.key == "payment").satisfied
    assert not project_income(
        (d,), {d.document_id: s}, {d.document_id: "held"}, [g]
    ).salary_evidence


def test_evidence_panel_and_document_preserve_context_and_database(tmp_path, monkeypatch):
    path = tmp_path / "salary.sqlite"
    seed_ordinary(path)
    monkeypatch.setenv("ANALISIS_NOMINAS_CANONICAL_DB", str(path))
    before = path.read_bytes()
    app = page()
    assert not app.exception
    assert any("Qué falta para acreditar el fijo" in x.label for x in app.expander)
    assert any("Modalidad de pagas" in df.value for df in app.dataframe)
    doc = app.session_state["panel_valid_ids"][0]
    app.selectbox(key="panel_income_document").select(doc).run()
    assert any("Requisito" in df.value for df in app.dataframe)
    app.multiselect(key="panel_income").set_value(["Bruto documental"]).run()
    assert any("Requisito" in df.value for df in app.dataframe)
    app.selectbox(key="panel_document").select(doc).run()
    assert not app.exception
    assert any("Requisito" in df.value for df in app.dataframe)
    app.button(key="panel_back").click().run()
    assert app.selectbox(key="panel_document").value is None
    assert path.read_bytes() == before
