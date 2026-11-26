"""Native R.1 filters and document navigation on synthetic SQLite only."""
from streamlit.testing.v1 import AppTest

from tests.integration import test_document_explorer as fixtures

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def page():
    return AppTest.from_file(str(fixtures.APP)).run(timeout=30)


def open_document(app, identity):
    app.selectbox(key='panel_open').select(identity).run()
    app.button(key='panel_open_button').click().run(timeout=30)
    assert not app.exception
    from streamlit.util import calc_hash
    app._page_hash = calc_hash('render_documents')
    return app


def reports(app):
    # Native page navigation by the same registered callable hash as Streamlit.
    from streamlit.util import calc_hash
    app._page_hash = calc_hash('render_documents')
    app.run(timeout=30)
    app.checkbox(key='document_reports').check().run(timeout=30)
    assert not app.exception
    return app


def test_history_month_detail_back_and_stale_selection(database):
    before = database.read_bytes()
    app = page()
    assert not app.exception
    assert app.title[0].value == 'Análisis de Nóminas'
    assert not app.metric
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert len(app.dataframe[0].value) == 1
    identity = app.session_state['panel_valid_ids'][0]
    open_document(app, identity)
    assert any(h.value == 'Ficha documental' for h in app.subheader)
    assert any(c.value == identity for c in app.code)
    app.button(key='panel_back').click().run()
    app._page_hash = ''
    assert app.text_input(key='panel_period').value == '03/2024'
    assert app.session_state['panel_document'] is None
    app.session_state['panel_document'] = identity
    app.text_input(key='panel_period').set_value('2025').run()
    assert app.session_state['panel_document'] is None
    assert len(app.dataframe[0].value) == 2
    assert database.read_bytes() == before


def test_intersection_unknown_invalid_empty_reset(database):
    app = page()
    app.selectbox(key='panel_company').select('Empresa Beta')
    app.text_input(key='panel_period').set_value('04/2025-05/2025').run()
    assert len(app.dataframe[0].value) == 2
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert any('No hay coincidencias' in x.value for x in app.info)
    app.text_input(key='panel_period').set_value('invalid').run()
    assert app.warning and not app.dataframe
    app.button(key='panel_reset').click().run()
    assert app.selectbox(key='panel_company').value is None
    assert app.text_input(key='panel_period').value == ''
    app.checkbox(key='panel_incomplete').check().run()
    assert len(app.dataframe[0].value) == 1
    assert set(app.dataframe[0].value['Bruto']) == {'—'}
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
    assert any('no hay importes' in x.value.lower() for x in app.info)
    open_document(app, identity)
    assert any(c.value == identity for c in app.code)
    assert any('1.234,56 €' in str(df.value) for df in app.dataframe)


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


def test_panel_navigation_has_exactly_two_native_pages(database, monkeypatch):
    import streamlit as st
    original = st.navigation
    captured: list[tuple[str, bool]] = []
    def navigation(pages, **kwargs):
        captured.extend((p.title, p._default) for p in pages)
        assert kwargs['position'] == 'sidebar'
        return original(pages, **kwargs)
    monkeypatch.setattr(st, 'navigation', navigation)
    app = page()
    assert captured == [('Análisis', True), ('Documentos', False)]
    assert not app.exception
    reports(app)
    assert any(e.label == 'Cobertura documental' for e in app.expander)
    assert any(t.value == 'Documentos' for t in app.title)
