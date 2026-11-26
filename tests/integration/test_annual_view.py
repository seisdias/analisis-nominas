"""Annual drill-down reuses contextual filters and documentary navigation."""

from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page, reports

database = fixtures.database
isolated_configuration = fixtures.isolated_configuration


def test_annual_view_filters_navigation_and_integrity(database):
    before = database.read_bytes()
    app = reports(page())
    assert not app.exception
    assert any(x.value == "Resumen económico por ejercicio" for x in app.subheader)
    assert any("Total anual" in df.value for df in app.dataframe)
    app.session_state["panel_company"] = "Empresa Beta"
    app.session_state["panel_period"] = "2025"
    app.run()
    app.selectbox(key="annual_group").select(("Empresa Beta", 2025)).run()
    assert not app.exception
    assert any("Bruto individual" in df.value for df in app.dataframe)
    identity = app.session_state["panel_valid_ids"][0]
    app.selectbox(key="annual_document").select(identity).run()
    app.button(key="annual_open").click().run()
    assert app.session_state["panel_document"] == identity
    assert any(x.value == "Ficha documental" for x in app.subheader)
    app.button(key="panel_back").click().run()
    assert app.selectbox(key="panel_company").value == "Empresa Beta"
    assert app.text_input(key="panel_period").value == "2025"
    assert database.read_bytes() == before


def test_visual_categories_do_not_remove_annual_inventory(database):
    app = reports(page())

    def annual():
        return next(df.value for df in app.dataframe if "Total anual" in df.value)

    before = annual().copy()
    app.session_state["panel_categories"] = []
    app.run()
    assert annual().equals(before)
    app.session_state["panel_period"] = "03/2024"
    app.run()
    assert not app.exception
    table = annual()
    assert set(table["Ventana"]) == {"03"}


def test_unavailable_annual_reader_does_not_break_other_views(database, monkeypatch):
    from src.canonical_inspection import InspectionError

    def fail(*args, **kwargs):
        raise InspectionError("synthetic")

    monkeypatch.setattr("src.annual_view.load_annual", fail)
    app = reports(page())
    assert not app.exception
    assert any("resumen anual" in e.value for e in app.error)
    assert any(e.value == "Documentos" for e in app.subheader)


def test_rejected_additivity_is_visible_separately_from_missing_contract(database, monkeypatch):
    from src.annual_summary import annual_summary
    from tests.unit.test_annual_additivity import record

    report = annual_summary(
        (record("a", currency="EUR"), record("b", currency="USD")), {}, {}, [], years=(2025, 2025)
    )
    monkeypatch.setattr("src.annual_view.load_annual", lambda *args, **kwargs: report)
    app = reports(page())
    assert not app.exception
    rows = next(df.value for df in app.dataframe if "Total anual" in df.value)
    assert set(rows["Aditividad"]) == {"Aditividad rechazada para este conjunto"}
    assert set(rows["Total anual"]) == {"No acreditado"}


def test_exploratory_sum_is_visible_without_promoting_annual_total(database):
    app = reports(page())
    app.session_state["panel_company"] = "Empresa Beta"
    app.session_state["panel_period"] = "2025"
    app.run()
    app.selectbox(key="annual_group").select(("Empresa Beta", 2025)).run()
    assert not app.exception
    assert any(x.value == "Suma documental exploratoria" for x in app.subheader)
    rows = next(df.value for df in app.dataframe if "Suma documental" in df.value)
    assert set(rows["Magnitud"]) == {"Bruto", "Neto"}
    assert any("No acredita el ingreso total" in x.value for x in app.caption)
    annual = next(df.value for df in app.dataframe if "Total anual" in df.value)
    assert set(annual["Total anual"]) == {"No acreditado"}


def test_exploratory_numeric_demo_uses_synthetic_values_only():
    from streamlit.testing.v1 import AppTest

    def demo():
        from dataclasses import replace

        from src.annual_view import _exploratory
        from tests.unit.test_documentary_sum import calculate, example

        group, rows = example()
        _exploratory(
            replace(
                group,
                exploratory=tuple(calculate(group, rows, series) for series in ("Bruto", "Neto")),
            )
        )

    app = AppTest.from_function(demo).run()
    assert not app.exception
    table = app.dataframe[0].value
    assert list(table["Suma documental"]) == ["191,34 EUR", "191,34 EUR"]
    assert list(table["Incluidos"]) == [2, 2]


def test_graphic_currency_provenance_and_net_only_sum_are_visible(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.unit.test_exceltic_currency import evidence

    proof = evidence(monkeypatch)
    assert proof is not None

    def screen(proof):
        from dataclasses import replace

        from src.annual_view import _exploratory
        from tests.unit.test_documentary_sum import calculate, example

        group, rows = example(amounts=(123456,), currency=None)
        rows[1]["currency_evidence"] = replace(
            proof,
            document_id="0",
            version_id=rows[1]["source_version_ids"][0],
            observation_id="0-Neto",
        )
        _exploratory(
            replace(
                group,
                exploratory=tuple(calculate(group, rows, series) for series in ("Bruto", "Neto")),
            )
        )

    app = AppTest.from_function(screen, args=(proof,)).run()
    assert not app.exception
    sums = app.dataframe[0].value
    assert list(sums["Estado"]) == ["blocked", "calculable"]
    trace = next(d.value for d in app.dataframe if "SHA símbolo" in d.value)
    assert trace.iloc[0]["Contrato"] == "exceltic-graphic-net-currency/c4.5-v1"
    assert "símbolo gráfico" in trace.iloc[0]["Evidencia"]
