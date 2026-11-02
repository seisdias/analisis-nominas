"""Read-only integration in the existing document/version navigation."""

from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page
from tests.integration.test_component_view import seed_components
from tests.integration.test_concepts_view import add_concepts, standalone

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def test_reconstruction_in_document_without_context_mutation(database):
    identity = seed_components(database)
    before = database.read_bytes()
    app = page()
    app.selectbox(key="panel_document").select(identity).run()
    assert not app.exception
    assert any(x.value == "Reconstrucción retributiva" for x in app.subheader)
    assert any(
        "Grupo retributivo" in df.value
        and "Bonus / variable" in df.value["Grupo retributivo"].tolist()
        for df in app.dataframe
    )
    assert any("No hay cobertura contractual" in x.value for x in app.info)
    app.button(key="panel_back").click().run()
    assert app.selectbox(key="panel_document").value is None
    assert database.read_bytes() == before


def test_versions_stay_separate_without_automatic_selection(database):
    identity, versions = add_concepts(database, multiple=True)
    before = database.read_bytes()
    app = standalone(database, identity)
    assert not any(x.value == "Reconstrucción retributiva" for x in app.subheader)
    for version in versions:
        app.selectbox(key="concept-version-" + identity).select(version).run()
        assert not app.exception
        assert any(x.value == "Reconstrucción retributiva" for x in app.subheader)
    assert database.read_bytes() == before
