from decimal import Decimal

from src.income_evolution import project_income
from src.income_view import income_chart
from tests.integration import test_analysis_panel
from tests.integration.test_analysis_panel import page
from tests.integration.test_income_view import isolated_configuration, seed_ordinary  # noqa: F401
from tests.unit.test_income_evolution import fixture

database = test_analysis_panel.database


def test_click_selection_is_bound_to_document():
    d, s, g = fixture()
    result = project_income((d,), {d.document_id: s}, {}, [g])
    spec = income_chart(result.rows).to_dict()
    assert any(p.get("select", {}).get("fields") == ["Documento"] for p in spec["params"])
    detail = result.compositions[d.document_id]
    assert len(detail.parts) == 3 and detail.earnings.difference == Decimal(0)


def test_gross_explorer_exposes_parts_and_survives_visibility(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.sqlite"
    seed_ordinary(path)
    monkeypatch.setenv("ANALISIS_NOMINAS_CANONICAL_DB", str(path))
    app = page()
    assert app.multiselect(key="panel_income").label == "Datos a analizar"
    picker = app.selectbox(key="panel_income_document")
    assert picker.value is None
    doc = app.session_state["panel_valid_ids"][0]
    picker.select(doc).run()
    assert not app.exception
    assert any("Partida del documento" in df.value for df in app.dataframe)
    app.multiselect(key="panel_income").set_value(["Bruto documental"]).run()
    assert app.selectbox(key="panel_income_document").value == doc
    assert any("Partida del documento" in df.value for df in app.dataframe)


def test_accredited_salary_only_with_complete_contract(monkeypatch):
    from src.income_evolution import COMPLETE, MONTHLY
    from src.salary_reconstruction import reconstruct
    from tests.unit.test_salary_reconstruction import contracts

    d, s, g = fixture()

    def series():
        return {r["Componente"]: r for r in project_income((d,), {d.document_id: s}, {}, [g]).rows}

    assert not {COMPLETE, MONTHLY}.intersection(series())
    monkeypatch.setattr("src.income_evolution.reconstruct", lambda e: reconstruct(e, *contracts(e)))
    visible = series()
    assert visible[COMPLETE]["Importe"] == 2500
    assert visible[MONTHLY]["Importe"] == 2550
    assert visible[MONTHLY]["Hecho"] and visible[MONTHLY]["Fórmula"]


def test_unlinked_total_does_not_get_other_extractions_composition():
    from dataclasses import replace

    d, s, g = fixture()
    other = replace(d, observation_facts=(("obs", ("unrelated",)),))
    assert not project_income((other,), {d.document_id: s}, {}, [g]).compositions


def test_restricted_document_never_offers_composition():
    d, s, g = fixture()
    projection = project_income((d,), {d.document_id: s}, {d.document_id: "Restricción local"}, [g])
    assert projection.rows == [] and not projection.compositions


def test_click_callback_transfers_only_document_identity(monkeypatch):
    from src import income_view

    state = {"chart_chart": {"selection": {"nomina": [{"Documento": "selected"}]}}}
    monkeypatch.setattr(income_view.st, "session_state", state)
    income_view._chart_document("chart")
    assert state["chart_document"] == "selected"


def test_native_chart_event_opens_correct_document(tmp_path, monkeypatch):
    """Exercise the widget event used by Streamlit's Vega selection listener."""
    import json

    path = tmp_path / "chart-event.sqlite"
    seed_ordinary(path)
    monkeypatch.setenv("ANALISIS_NOMINAS_CANONICAL_DB", str(path))
    app = page()
    identity = app.session_state["panel_valid_ids"][-1]
    chart = next(c for c in app.get("vega_lite_chart") if c.proto.id.endswith("panel_income_chart"))
    states = app._tree.get_widget_states()
    event = states.widgets.add()
    event.id = chart.proto.id
    event.string_value = json.dumps({"selection": {"nomina": [{"Documento": identity}]}})
    app._run(states)
    assert not app.exception
    assert app.selectbox(key="panel_income_document").value == identity
    assert any("Partida del documento" in df.value for df in app.dataframe)


def test_unknown_concept_and_signed_difference_remain_visible(database, monkeypatch):
    from dataclasses import replace

    from tests.unit.test_salary_reconstruction import rebuild

    d, s, g = fixture()
    e = s.extractions[0]
    extra = next(c for c in e.concepts if c.get("codigo").fact.value.value == "9032")
    e = rebuild(
        e,
        {
            extra.get("concepto").fact.fact_key: "Partida sintética",
            "nomina.total_devengado": 280001,
        },
    )
    total = next(f for f in e.facts if f.fact.fact_key == "nomina.total_devengado")
    d = replace(d, observation_facts=(("obs", (total.fact.fact_id,)),))
    result = project_income(
        (d,),
        {d.document_id: replace(s, extractions=(e,))},
        {},
        [dict(g, Importe=2800.01, **{"Importe exacto": "2.800,01 €"})],
    )
    assert result.compositions[d.document_id].earnings.difference == Decimal("-0.01")
    monkeypatch.setattr("src.income_view.load_income", lambda *a, **k: result)
    app = page()
    app.selectbox(key="panel_income_document").select(d.document_id).run()
    assert not app.exception
    assert any("Diferencia no explicada" in msg.value for msg in app.markdown)
    assert any(
        "Grupo" in df.value and "Sin clasificación suficiente" in set(df.value["Grupo"])
        for df in app.dataframe
    )
