"""Shared component controls are visual only; SQLite is synthetic and read-only."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from src.component_view import component_chart, load_components, visibility_subset
from src.economic_components import component_rows
from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page
from tests.unit.test_economic_components import example, run

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def test_point_only_chart_trace_and_independent_subset():
    doc,source=example(count=2)
    result=run(doc,source)
    spec=component_chart(component_rows(result.points)).to_dict()
    assert spec['mark']['type']=='point'
    assert not spec.get('transform') and 'aggregate' not in str(spec)
    assert spec['encoding']['x']['title']=='Periodo del documento'
    assert len(spec['data']['values'])==2
    assert visibility_subset(result.points,())==()
    assert visibility_subset(result.points,('Bonus / variable',))==result.points
    assert result==run(doc,source)
    assert component_chart([]).to_dict()['data']['values']==[]


def test_shared_selection_retains_hidden_preferences_and_reset():
    app=AppTest.from_string('''
import streamlit as st
from src.component_view import component_visibility
context=st.selectbox('Contexto', ['all','bonus','prorata'])
options={'Bonus / variable','Prorratas de extras'} if context=='all' else {('Bonus / variable' if context=='bonus' else 'Prorratas de extras')}
st.write(component_visibility(options,key='test_components'))
''').run()
    assert set(app.multiselect[0].value)=={'Bonus / variable','Prorratas de extras'}
    app.multiselect[0].set_value(['Prorratas de extras']).run()
    app.selectbox[0].select('prorata').run()
    app.selectbox[0].select('bonus').run()
    assert app.multiselect[0].value==[]
    app.button(key='test_components_reset').click().run()
    assert app.multiselect[0].value==['Bonus / variable']
    assert app.selectbox[0].value=='bonus' and not app.exception


def test_context_filter_and_ficha_do_not_create_empty_controls(database):
    before=database.read_bytes()
    app=page()
    assert not app.exception
    assert not any(m.label=='Componentes económicos visibles' for m in app.multiselect)
    app.selectbox(key='panel_company').select('Empresa Alfa').run()
    ids=app.session_state['panel_valid_ids']
    app.selectbox(key='panel_document').select(ids[0]).run()
    assert not app.exception
    app.button(key='panel_back').click().run()
    assert app.selectbox(key='panel_company').value=='Empresa Alfa'
    assert database.read_bytes()==before


def test_reader_no_synthetic_parser_correspondence(database):
    from src.analytic_dataset import load_analytic_dataset
    from tests.integration.test_concepts_view import add_concepts
    add_concepts(database)
    before=database.read_bytes()
    result=load_components(database,load_analytic_dataset(database),{})
    assert not result.points
    assert database.read_bytes()==before


def test_multiversion_and_total_independence():
    from src.payroll_timeline import classified_timeline
    from tests.unit.test_payroll_timeline import record
    doc,source=example()
    multi=replace(doc,provenance=doc.provenance+(replace(doc.provenance[0],version_id='second'),))
    assert not run(multi,source).points
    total=classified_timeline([record(doc=doc.document_id,versions=('first','second'))],(multi,),years=(2025,2025))
    assert total.points  # existing certified total contract is unchanged


def seed_components(database):
    """New synthetic extraction, keeping the original total evidence untouched."""
    import sqlite3

    from src.canonical.documents import Extraction, extraction_id
    from src.canonical.facts import DocumentaryFact
    from src.canonical_inspection import open_inspector
    from src.persistence.economics import EconomicRepository
    from tests.unit.test_document_concepts import fact
    with open_inspector(database) as inspector:
        identity=inspector.documents(company='Empresa Alfa')[0]['document_id']
        version=inspector.document(identity)['versions'][0]
        old=version['extractions'][0]
        old_facts=inspector.extraction_facts(old.extraction_id)
    with sqlite3.connect(database) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute("UPDATE logical_documents SET document_type='NOMINA_ORDINARIA' WHERE document_id=?",(identity,))
        repo=EconomicRepository(conn)
        new=Extraction(extraction_id(old.version_id,'alten-legacy-evidence','synthetic','d'*64),
                       old.version_id,'alten-legacy-evidence','synthetic','d'*64,'e'*64)
        repo.register_extraction(new)
        repo.register_fact(fact('nomina.tipo','NOMINA_ORDINARIA',ext=old.extraction_id))
        for f in old_facts:
            from src.canonical.facts import FactDraft
            repo.register_fact(DocumentaryFact.from_draft(new.extraction_id,FactDraft(f.fact_key,f.value)))
        repo.register_fact(fact('nomina.tipo','NOMINA_ORDINARIA',ext=new.extraction_id))
        for n,(code,label,category) in enumerate([('9122','Bono','bono'),('9016','P.P. Extra Verano','paga_extra_incluida')]):
            for k,v in [('codigo',code),('concepto',label),('categoria',category),('columna','devengos'),('atraso','false'),('importe',12345)]:
                repo.register_fact(fact(f'payload/conceptos/{n}/{k}',v,ext=new.extraction_id))
    return identity


def test_panel_components_independent_of_categories_coverage_and_navigation(database):
    identity=seed_components(database)
    before=database.read_bytes()
    app=page()
    assert not app.exception
    assert set(app.multiselect(key='panel_components').value)=={'Bonus / variable','Prorratas de extras'}
    inventory=app.metric[0].value
    app.multiselect(key='panel_categories').set_value([]).run()
    assert app.metric[0].value==inventory
    assert len(app.multiselect(key='panel_components').value)==2
    app.multiselect(key='panel_components').set_value(['Prorratas de extras']).run()
    app.selectbox(key='panel_document').select(identity).run()
    assert app.multiselect(key='panel_components').value==['Prorratas de extras']
    assert any('1.234,56 €' in str(d.value) for d in app.dataframe)
    app.button(key='panel_back').click().run()
    assert app.multiselect(key='panel_components').value==['Prorratas de extras']
    app.selectbox(key='panel_company').select('Empresa Beta').run()
    assert not any(m.label=='Componentes económicos visibles' for m in app.multiselect)
    app.selectbox(key='panel_company').select('Empresa Alfa').run()
    assert app.multiselect(key='panel_components').value==['Prorratas de extras']
    app.text_input(key='panel_period').set_value('03/2024').run()
    assert app.multiselect(key='panel_components').value==['Prorratas de extras']
    app.button(key='panel_components_reset').click().run()
    assert app.multiselect(key='panel_categories').value==[]
    assert len(app.multiselect(key='panel_components').value)==2
    assert database.read_bytes()==before and not app.exception


def test_history_components_ignore_total_series_visibility_and_reader_is_shared(database):
    seed_components(database)
    from tests.integration.test_payroll_timeline import page as history
    app=history()
    assert not app.exception
    assert len(app.multiselect(key='timeline_components').value)==2
    app.multiselect(key='timeline_series').set_value([]).run()
    app.multiselect(key='timeline_categories').set_value([]).run()
    assert len(app.multiselect(key='timeline_components').value)==2
    assert len(app.get('vega_lite_chart'))==1
    assert any('incluidos posibles conceptos extraordinarios' in c.value for c in app.caption)
    app.multiselect(key='timeline_components').set_value([]).run()
    assert not app.get('vega_lite_chart')
    assert any('ocultos' in i.value for i in app.info)
    app.button(key='timeline_components_reset').click().run()
    assert len(app.get('vega_lite_chart'))==1


def test_local_restrictions_apply_before_document_visibility(database,monkeypatch):
    identity=seed_components(database)
    from src.cli_config import load_config
    config=replace(load_config(),withheld_document_ids=(identity,))
    monkeypatch.setattr('src.analysis_panel.load_config',lambda:config)
    app=page()
    app.selectbox(key='panel_document').select(identity).run()
    assert not any(m.label=='Componentes económicos visibles' for m in app.multiselect)
    assert not app.get('vega_lite_chart') and not app.exception


def test_component_query_error_is_explained_without_changing_filters(database,monkeypatch):
    from src.canonical_inspection import InspectionError
    def unavailable(*args,**kwargs):
        raise InspectionError('synthetic failure')
    monkeypatch.setattr('src.component_view.load_components',unavailable)
    app=page()
    assert not app.exception
    assert any('desglose en solo lectura' in e.value for e in app.error)
    assert app.metric[0].value=='4'
    assert app.selectbox(key='panel_document').value is None


def test_incompatible_component_currency_warning_is_visible(database,monkeypatch):
    from src.economic_components import ComponentProjection
    monkeypatch.setattr('src.component_view.load_components',lambda *a,**k:
                        ComponentProjection((),(('synthetic','Concepto con divisa explícita incompatible con EUR'),)))
    app=page()
    assert any('divisa explícita incompatible' in w.value for w in app.warning)
    assert not app.exception
