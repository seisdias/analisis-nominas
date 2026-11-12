"""Annual drill-down reuses contextual filters and documentary navigation."""

from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page

database = fixtures.database
isolated_configuration = fixtures.isolated_configuration


def test_annual_view_filters_navigation_and_integrity(database):
    before = database.read_bytes()
    app = page()
    assert not app.exception
    assert any(x.value == "Resumen económico por ejercicio" for x in app.subheader)
    assert any("Total anual" in df.value for df in app.dataframe)
    app.selectbox(key="panel_company").select("Empresa Beta")
    app.text_input(key="panel_period").set_value("2025").run()
    app.selectbox(key="annual_group").select(("Empresa Beta", 2025)).run()
    assert not app.exception
    assert any("Bruto individual" in df.value for df in app.dataframe)
    identity = app.session_state["panel_valid_ids"][0]
    app.selectbox(key="annual_document").select(identity).run()
    app.button(key="annual_open").click().run()
    assert app.selectbox(key="panel_document").value == identity
    assert any(x.value == "Ficha documental" for x in app.subheader)
    app.button(key="panel_back").click().run()
    assert app.selectbox(key="panel_company").value == "Empresa Beta"
    assert app.text_input(key="panel_period").value == "2025"
    assert database.read_bytes() == before


def test_visual_categories_do_not_remove_annual_inventory(database):
    app = page()

    def annual():
        return next(df.value for df in app.dataframe if "Total anual" in df.value)

    before = annual().copy()
    app.multiselect(key="panel_categories").set_value([]).run()
    assert annual().equals(before)
    app.text_input(key="panel_period").set_value("03/2024").run()
    assert not app.exception
    table = annual()
    assert set(table["Ventana"]) == {"03"}


def test_unavailable_annual_reader_does_not_break_other_views(database, monkeypatch):
    from src.canonical_inspection import InspectionError

    def fail(*args, **kwargs):
        raise InspectionError("synthetic")

    monkeypatch.setattr("src.annual_view.load_annual", fail)
    app = page()
    assert not app.exception
    assert any("resumen anual" in e.value for e in app.error)
    assert any(e.value == "Documentos disponibles" for e in app.subheader)


def test_rejected_additivity_is_visible_separately_from_missing_contract(database, monkeypatch):
    from src.annual_summary import annual_summary
    from tests.unit.test_annual_additivity import record

    report = annual_summary(
        (record("a", currency="EUR"), record("b", currency="USD")), {}, {}, [], years=(2025, 2025)
    )
    monkeypatch.setattr("src.annual_view.load_annual", lambda *args, **kwargs: report)
    app = page()
    assert not app.exception
    rows = next(df.value for df in app.dataframe if "Total anual" in df.value)
    assert set(rows["Aditividad"]) == {"Aditividad rechazada para este conjunto"}
    assert set(rows["Total anual"]) == {"No acreditado"}
