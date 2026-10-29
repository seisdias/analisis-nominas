"""Classification/diagnosis preserve the existing synthetic document navigation."""

from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page
from tests.integration.test_component_view import seed_components
from tests.integration.test_concepts_view import add_concepts, standalone

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def test_classification_visible_without_new_certification_or_changes(database):
    identity = seed_components(database)
    before = database.read_bytes()
    app = page()
    app.selectbox(key="panel_document").select(identity).run()
    assert not app.exception
    assert any("Clasificación y conciliación económica" in x.value for x in app.subheader)
    assert any(
        "Función económica" in df.value
        and "Bonus / variable / incentivo" in df.value["Función económica"].tolist()
        for df in app.dataframe
    )
    assert any(
        "Diagnóstico" in df.value and "Desglose incompleto" in df.value["Diagnóstico"].tolist()
        for df in app.dataframe
    )
    assert any("1.234,56 €" in str(df.value) for df in app.dataframe)
    app.button(key="panel_back").click().run()
    assert app.selectbox(key="panel_document").value is None
    assert database.read_bytes() == before


def test_multiversion_requires_explicit_choice_and_no_joined_diagnosis(database):
    identity, versions = add_concepts(database, multiple=True)
    before = database.read_bytes()
    app = standalone(database, identity)
    assert not any("Clasificación y conciliación económica" in x.value for x in app.subheader)
    for version in versions:
        app.selectbox(key="concept-version-" + identity).select(version).run()
        assert not app.exception
        assert any("Clasificación y conciliación económica" in x.value for x in app.subheader)
    assert database.read_bytes() == before
