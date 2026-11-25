"""One visual plot, real dates and visual-only series selection."""
import json
from copy import deepcopy

import pytest

from src.income_evolution import project_income
from src.income_view import income_chart
from tests.integration.test_analysis_panel import open_document, page
from tests.integration.test_document_explorer import isolated_configuration  # noqa: F401
from tests.integration.test_income_view import seed_ordinary
from tests.unit.test_income_evolution import fixture


@pytest.mark.parametrize('start,end,format_', [
    ('2025-06-01', '2025-08-01', '%m/%Y'),
    ('2024-01-01', '2025-12-01', '%Y'),
    ('2006-01-01', '2025-12-01', '%Y'),
])
def test_single_plot_dates_companies_gaps_and_exact_values(start, end, format_):
    d, s, g = fixture()
    rows = project_income((d,), {d.document_id: s}, {}, [g]).rows
    rows += [dict(r, Fecha='2025-09-01', Empresa='Otra empresa', Documento='otro') for r in rows]
    rows.reverse()
    before = deepcopy(rows)
    spec = income_chart(rows, technical=False, period=(start, end)).to_dict()
    assert 'facet' not in spec and 'layer' not in spec and 'concat' not in spec
    assert spec['encoding']['x']['type'] == 'temporal'
    assert spec['encoding']['x']['scale']['type'] == 'utc'
    assert spec['encoding']['x']['axis']['format'] == format_
    assert spec['encoding']['x']['scale']['domain'] == [start, end]
    assert spec['encoding']['shape']['field'] == 'Empresa'
    assert spec['mark']['type'] == 'point'  # No links over gaps or independent documents.
    plotted = spec['data']['values']
    assert [r['Fecha'] for r in plotted] == sorted(r['Fecha'] for r in rows)
    assert sorted(r['Importe'] for r in plotted) == sorted(r['Importe'] for r in rows)
    assert len(plotted) == len(rows) and rows == before
    assert 'aggregate' not in str(spec) and 'interpolate' not in str(spec)
    assert all(word not in str(spec['encoding']).lower() for word in
               ('acreditad', 'certific', 'presentación', 'representación', 'versión', 'extracción'))


def test_selector_keeps_table_and_context_on_return(tmp_path, monkeypatch):
    path = tmp_path / 'ordinary.sqlite'
    seed_ordinary(path)
    before = path.read_bytes()
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    app = page()
    assert len(app.multiselect) == 1
    assert len(app.get('vega_lite_chart')) == 1
    spec = json.loads(app.get('vega_lite_chart')[0].proto.spec)
    assert 'facet' not in spec
    original = app.dataframe[0].value.copy()
    app.multiselect(key='panel_series').set_value([]).run()
    assert app.dataframe[0].value.equals(original)
    assert not app.get('vega_lite_chart')
    assert any('series' in i.value.lower() for i in app.info)
    app.multiselect(key='panel_series').set_value(['Bruto documental']).run()
    assert len(app.get('vega_lite_chart')) == 1
    assert app.dataframe[0].value.equals(original)
    app.selectbox(key='panel_company').select('Empresa Uno').run()
    app.text_input(key='panel_period').set_value('06/2025 – 08/2025').run()
    assert set(app.dataframe[0].value['Periodo']) == {'06/2025', '07/2025'}
    identity = app.session_state['panel_valid_ids'][0]
    open_document(app, identity)
    app.button(key='panel_back').click().run()
    app._page_hash = ''
    assert app.multiselect(key='panel_series').value == ['Bruto documental']
    assert app.text_input(key='panel_period').value == '06/2025 – 08/2025'
    assert app.selectbox(key='panel_company').value == 'Empresa Uno'
    app.button(key='panel_reset').click().run()
    assert len(app.multiselect(key='panel_series').value) > 1
    assert path.read_bytes() == before


def test_main_text_is_plain_and_table_follows_chart(tmp_path, monkeypatch):
    path = tmp_path / 'ordinary.sqlite'
    seed_ordinary(path)
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    app = page()
    text = ' '.join(str(e.value) for kind in (app.caption, app.markdown, app.info,
        app.warning, app.subheader) for e in kind)
    assert all(word not in text.lower() for word in (
        'acreditad', 'certific', 'presentación', 'representación', 'evidence_only',
        'aditividad', 'conciliación', 'extracción', 'documento lógico'))
    elements = list(app.main)
    chart_index = next(i for i,e in enumerate(elements) if e.type == 'vega_lite_chart')
    table_index = next(i for i,e in enumerate(elements) if e.type == 'dataframe')
    assert chart_index < table_index
    assert not any(e.type in ('expander', 'multiselect', 'selectbox')
                   for e in elements[chart_index+1:table_index])
    assert list(app.dataframe[0].value.columns)[:5] == ['Periodo', 'Empresa', 'Tipo', 'Bruto', 'Neto']
