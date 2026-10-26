"""Native filter state and document navigation on synthetic SQLite only."""
from streamlit.testing.v1 import AppTest

from tests.integration import test_document_explorer as fixtures

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def page():
    return AppTest.from_string('from src.analysis_panel import render_panel\nrender_panel()').run(timeout=30)


def test_history_month_detail_back_and_stale_selection(database):
    before = database.read_bytes()
    app = page()
    assert not app.exception
    assert app.title[0].value == 'Panel de análisis'
    assert app.metric[0].value == '4'
    assert app.selectbox(key='panel_document').value is None
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert app.metric[0].value == '1'
    assert not app.get('vega_lite_chart')
    assert app.selectbox(key='panel_document').value is None
    identity = app.selectbox(key='panel_document').options[1]
    # Select the full stored ID, never the formatted option or first candidate implicitly.
    ids = app.session_state['panel_valid_ids']
    app.selectbox(key='panel_document').select(ids[0]).run()
    assert not app.exception
    assert any(h.value == 'Ficha documental' for h in app.subheader)
    assert any(c.value == ids[0] for c in app.code)
    assert identity != ids[0]
    app.button(key='panel_back').click().run()
    assert app.text_input(key='panel_period').value == '03/2024'
    assert app.selectbox(key='panel_document').value is None
    app.selectbox(key='panel_document').select(ids[0]).run()
    app.text_input(key='panel_period').set_value('2025').run()
    assert app.selectbox(key='panel_document').value is None
    assert app.metric[0].value == '2'
    assert any('selección documental' in x.value for x in app.info)
    assert database.read_bytes() == before


def test_intersection_unknown_invalid_empty_reset(database):
    app = page()
    app.selectbox(key='panel_company').select('Empresa Beta')
    app.text_input(key='panel_period').set_value('04/2025-05/2025').run()
    assert app.metric[0].value == '2'
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert any('No hay coincidencias' in x.value for x in app.info)
    assert app.selectbox(key='panel_company').value == 'Empresa Beta'
    app.text_input(key='panel_period').set_value('invalid').run()
    assert app.warning and not app.dataframe
    app.button(key='panel_reset').click().run()
    assert app.selectbox(key='panel_company').value is None
    assert app.text_input(key='panel_period').value == ''
    app.checkbox(key='panel_incomplete').check().run()
    assert app.metric[0].value == '1'
    assert not app.exception


def test_panel_preserves_local_hold_and_traceability(database, monkeypatch):
    from dataclasses import replace

    from src.analysis_panel import load_panel
    from src.cli_config import load_config
    snapshot = load_panel(database)
    identity = next(d.document_id for d in snapshot.coverage if d.company == 'Empresa Alfa')
    config = replace(load_config(), withheld_document_ids=(identity,))
    monkeypatch.setattr('src.analysis_panel.load_config', lambda: config)
    app = page()
    app.selectbox(key='panel_company').select('Empresa Alfa').run()
    assert not app.get('vega_lite_chart')
    assert any('restric' in x.value.lower() for x in app.warning)
    app.selectbox(key='panel_document').select(identity).run()
    assert any(c.value == identity for c in app.code)
    assert any('1.234,56 €' in str(df.value) for df in app.dataframe)
    assert not app.exception


def test_empty_database_and_unavailable(tmp_path, monkeypatch):
    from src.persistence import open_database
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    app = page()
    assert not app.exception and any('No hay coincidencias' in i.value for i in app.info)
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(tmp_path / 'absent.sqlite'))
    assert page().error


def test_panel_navigation_keeps_previous_pages(database):
    app = AppTest.from_file(str(fixtures.APP)).run()
    labels = [getattr(item, 'label', None) for item in app.get('page_link')]
    assert all(label in labels for label in ('Panel de análisis', 'Explorador', 'Evolución histórica', 'Cobertura documental'))
    assert not app.exception


def test_category_visibility_preserves_coverage_context_and_detail(database):
    app = page()
    category = 'Documentos sin clasificar'
    assert app.multiselect(key='panel_categories').value == [category]
    app.multiselect(key='panel_categories').set_value([]).run()
    assert app.metric[0].value == '4'
    assert not app.get('vega_lite_chart')
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert app.multiselect(key='panel_categories').value == []
    assert app.metric[0].value == '1'
    identity = app.session_state['panel_valid_ids'][0]
    app.selectbox(key='panel_document').select(identity).run()
    assert any(c.value == identity for c in app.code)
    app.button(key='panel_back').click().run()
    assert app.multiselect(key='panel_categories').value == []
    app.button(key='panel_categories_reset').click().run()
    assert app.multiselect(key='panel_categories').value == [category]
    assert app.text_input(key='panel_period').value == '03/2024'
    assert not app.exception


def test_multiple_categories_independent_and_preferences_survive_context(database, monkeypatch):
    from dataclasses import replace

    from src.analysis_panel import load_panel
    from src.analytic_dataset import DocumentCategory as C
    snapshot = load_panel(database)
    kinds = [C.ORDINARY, C.EXTRA, C.VARIABLE_BONUS, C.UNCLASSIFIED]
    coverage = tuple(replace(d, document=replace(d.document, category=c))
                     for d, c in zip(snapshot.coverage, kinds, strict=True))
    monkeypatch.setattr('src.analysis_panel.load_panel', lambda *args: replace(snapshot, coverage=coverage))
    app = page()
    widget = app.multiselect(key='panel_categories')
    assert len(widget.value) == 4
    for category in ('Pagas extraordinarias', 'Variables / bonus'):
        app.multiselect(key='panel_categories').set_value([category]).run()
        assert app.metric[0].value == '4'
        assert app.dataframe[-1].value.shape[0] == 4  # Complete inventory.
        assert set(app.dataframe[-2].value['Categoría']) == {category}
    app.selectbox(key='panel_company').select('Empresa Alfa').run()
    assert app.multiselect(key='panel_categories').value == ['Variables / bonus']
    app.selectbox(key='panel_company').select(None).run()
    assert app.multiselect(key='panel_categories').value == ['Variables / bonus']
    assert not app.exception
