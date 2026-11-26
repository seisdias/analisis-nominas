"""R.1 navigation contract, using synthetic canonical data."""
from streamlit.testing.v1 import AppTest

from tests.integration import test_document_explorer as fixtures

APP = fixtures.APP
database = fixtures.database
isolated_configuration = fixtures.isolated_configuration


def test_two_native_pages_and_clean_initial_analysis(database):
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert app.title[0].value == 'Análisis de Nóminas'
    assert not app.metric
    assert app.text_input(key='panel_period').value == ''
    assert list(app.dataframe[0].value.columns) == ['Periodo', 'Empresa', 'Tipo', 'Bruto', 'Neto']
    assert not app.code


def test_chart_reuses_projection_without_technical_tooltips():
    from copy import deepcopy

    from src.income_evolution import project_income
    from src.income_view import income_chart
    from tests.unit.test_income_evolution import fixture

    document, source, gross = fixture()
    result = project_income((document,), {document.document_id: source}, {}, [gross])
    original = deepcopy(result.rows)
    spec = income_chart(result.rows, technical=False).to_dict()
    assert result.rows == original
    assert [r['Importe'] for r in spec['data']['values']] == [r['Importe'] for r in original]
    assert 'aggregate' not in str(spec) and 'interpolate' not in str(spec)
    tooltips = str(spec['encoding']['tooltip'])
    assert all(x not in tooltips for x in ('Documento', 'Hecho', 'Versión', 'Fórmula'))


def test_unknown_totals_do_not_become_zero_or_candidates(database):
    from src.analysis_context import ContextFilters, build_context
    from src.analysis_panel import _economic_rows, load_panel

    snapshot = load_panel(database)
    context = build_context(snapshot.coverage, ContextFilters())
    rows = _economic_rows(snapshot, context)
    assert len(rows) == 4
    assert [r['Bruto'] for r in rows].count('—') == 3
    assert [r['Bruto'] for r in rows].count('1.234,56 €') == 1
    assert all(r['Bruto'] == r['Neto'] for r in rows)
    assert all('Documento' not in r and 'Versiones' not in r for r in rows)


def test_row_selection_opens_document_and_back_does_not_reopen(database):
    from streamlit.util import calc_hash

    from tests.integration.test_analysis_panel import page

    app = page()
    app.text_input(key='panel_period').set_value('03/2024').run()
    identity = app.session_state['panel_valid_ids'][0]
    key = next(k for k in app.session_state.filtered_state if k.startswith('panel_table_'))
    app.session_state[key] = {'selection': {'rows': [0], 'columns': [], 'cells': []}}
    app.run()
    assert not app.exception
    assert app.session_state['panel_document'] == identity
    assert any(h.value == 'Ficha documental' for h in app.subheader)
    app._page_hash = calc_hash('render_documents')
    app.button(key='panel_back').click().run()
    app._page_hash = ''
    app.run()
    assert not app.exception
    assert app.title[0].value == 'Análisis de Nóminas'
    assert app.text_input(key='panel_period').value == '03/2024'
    assert not app.code


def test_existing_document_selection_does_not_narrow_analysis(database):
    from tests.integration.test_analysis_panel import page

    app = page()
    app.session_state['panel_document'] = app.session_state['panel_valid_ids'][0]
    app.run()
    assert len(app.dataframe[0].value) == 4
    assert not app.metric and not app.code


def test_main_chart_opens_selected_document(tmp_path, monkeypatch):
    import json

    from tests.integration.test_analysis_panel import page
    from tests.integration.test_income_view import seed_ordinary

    path = tmp_path / 'chart.sqlite'
    seed_ordinary(path)
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    app = page()
    identity = app.session_state['panel_valid_ids'][-1]
    chart = app.get('vega_lite_chart')[0]
    states = app._tree.get_widget_states()
    event = states.widgets.add()
    event.id = chart.proto.id
    event.string_value = json.dumps({'selection': {'nomina': [{'Documento': identity}]}})
    app._run(states)
    assert not app.exception
    assert app.session_state['panel_document'] == identity
    assert any(h.value == 'Ficha documental' for h in app.subheader)


def test_coverage_loads_when_opened_in_documents(database):
    from streamlit.util import calc_hash

    from tests.integration.test_analysis_panel import page

    app = page()
    app._page_hash = calc_hash('render_documents')
    app.run()
    assert not any(m.label == 'Documentos lógicos' for m in app.metric)
    app.session_state['documents_coverage'] = True
    app.run()
    assert not app.exception
    assert any(m.label == 'Documentos lógicos' for m in app.metric)
    assert any(h.value == 'Empresas, años y meses documentados' for h in app.subheader)
