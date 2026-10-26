"""Real read-only inspector and Streamlit page on synthetic canonical databases."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical_inspection import open_inspector
from src.payroll_timeline import prepare_timeline, timeline_chart
from src.persistence import connect, open_database
from src.persistence.economics import EconomicRepository
from tests.integration import test_document_explorer as fixtures

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database

def page():
    return AppTest.from_string('from src.payroll_timeline import render_timeline\nrender_timeline()').run(timeout=20)


def test_real_records_candidates_filters_and_read_only(database):
    before = database.read_bytes()
    files = set(database.parent.iterdir())
    with open_inspector(database) as inspector:
        records = inspector.timeline_records()
    assert len(records) == 10  # Four documents; two gross/net alternatives in one.
    candidates = [r for r in records if r['document_status'] == 'ambiguous']
    assert len(candidates) == 4
    assert len({r['observation_id'] for r in candidates}) == 4
    assert all(r['value']['status'] == 'certified' for r in candidates)
    result = prepare_timeline(records, years=(2006, 2025))
    assert len(result.points) == 2
    assert result.ambiguous_periods == 1
    assert all(r['eligibility'] in (None, 'evidence_only') for r in records)
    app = page()
    assert not app.exception
    assert len(app.get('vega_lite_chart')) == 1
    assert len(app.dataframe[0].value) == 10
    app.selectbox[0].select('Empresa Beta').run()
    assert len(app.dataframe[0].value) == 6
    assert not app.get('vega_lite_chart')
    app.selectbox[0].select('Empresa Alfa')
    app.multiselect[0].set_value(['Neto']).run()
    assert list(app.dataframe[0].value['Serie']) == ['Neto']
    app.slider[0].set_range(2025, 2025).run()
    assert not app.get('vega_lite_chart')
    assert database.read_bytes() == before
    assert set(database.parent.iterdir()) == files


def test_empty_missing_and_query_errors(tmp_path, monkeypatch):
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    assert 'No hay documentos' in page().info[0].value
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(tmp_path/'missing.sqlite'))
    assert page().error
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB')
    assert page().warning


def test_chart_has_no_aggregation_and_monthly_domain(database):
    with open_inspector(database) as inspector:
        points = prepare_timeline(inspector.timeline_records(), years=(2006, 2025)).points
    spec = timeline_chart(points, '2006-01-01', '2025-05-01').to_dict()
    assert 'transform' not in spec
    assert all('aggregate' not in encoding for encoding in spec['encoding'].values() if isinstance(encoding, dict))
    assert spec['encoding']['x']['scale']['domain'] == ['2006-01-01', '2025-05-01']
    assert spec['encoding']['detail']['field'] == 'Tramo'
    assert spec['encoding']['color']['field'] == 'Empresa'
    assert spec['encoding']['strokeDash']['field'] == 'Serie'


def add_version_or_document(path, new_document):
    with connect(path, mode='read_write') as connection:
        repo = EconomicRepository(connection)
        old = connection.execute("SELECT document_id FROM logical_documents WHERE origin_key='certified'").fetchone()[0]
        doc = repo.get_document(old)
        assert doc is not None
        original = repo.get_document_versions(old)[0]
        extid = connection.execute('SELECT extraction_id FROM extractions WHERE version_id=?', (original.version_id,)).fetchone()[0]
        if new_document:
            doc = LogicalDocument(document_id(doc.corpus_id, 'second'), doc.corpus_id, None, 'unknown', 'second')
            repo.register_document(doc)
        ver = DocumentVersion(version_id(doc.document_id, original.file_id, 'another'), doc.document_id, original.file_id, 'another')
        repo.register_version(ver)
        ext = Extraction(extraction_id(ver.version_id, 'synthetic', '1', 'd'*64), ver.version_id, 'synthetic', '1', 'd'*64, 'e'*64)
        repo.register_extraction(ext)
        for fact in repo.get_extraction_facts(extid):
            repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(fact.fact_key, fact.value)))
        # Existing unique observations retain their version support. Never create
        # observations for the additional version/document in this test.


def test_multiple_versions_use_existing_unique_observation(database):
    add_version_or_document(database, False)
    with open_inspector(database) as inspector:
        records = [r for r in inspector.timeline_records() if r['company_text'] == 'Empresa Alfa']
    assert all(len(r['version_ids']) == 2 and len(r['source_version_ids']) == 1 for r in records)
    assert len(prepare_timeline(records, years=(2006, 2025)).points) == 2


def test_second_document_same_month_is_retained_and_blocks_unique_point(database):
    add_version_or_document(database, True)
    with open_inspector(database) as inspector:
        result = prepare_timeline(inspector.timeline_records(), company='Empresa Alfa', years=(2006, 2025))
    assert result.points == []
    assert result.ambiguous_periods == 1
    assert len(result.table) == 4
    assert len({r['Documento'] for r in result.table}) == 2


def test_existing_navigation_keeps_explorer_and_adds_timeline(database):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2]/'app.py')).run()
    assert not app.exception
    assert app.title[0].value == 'Análisis de Nóminas'
    labels = [getattr(link, 'label', None) for link in app.get('page_link')]
    assert 'Explorador' in labels and 'Evolución histórica' in labels


def test_optional_average_keeps_original_chart_and_table(database):
    app = page()
    original = app.get('vega_lite_chart')[0].proto.spec
    table = app.dataframe[0].value.copy()
    assert not app.checkbox[0].value
    app.checkbox[0].check().run()
    assert not app.exception
    assert any('0 puntos' in item.value for item in app.info)
    assert any('No constituye salario certificado' in item.value for item in app.caption)
    assert app.dataframe[0].value.equals(table)
    app.checkbox[0].uncheck().run()
    assert app.get('vega_lite_chart')[0].proto.spec == original


def test_average_visible_with_legend_and_unchanged_documentary_points(database, monkeypatch):
    from src.analytic_dataset import DocumentCategory
    from src.payroll_timeline import moving_average
    from tests.unit.test_payroll_timeline import analytic, year_records

    rows = year_records()
    monkeypatch.setattr('src.canonical_inspection.CanonicalInspector.timeline_records', lambda self: rows)
    monkeypatch.setattr('src.payroll_timeline.load_analytic_dataset',
        lambda path: [analytic(f'd{m}', DocumentCategory.ORDINARY) for m in range(1, 13)])
    app = page()
    table = app.dataframe[0].value.copy()
    app.checkbox[0].check().run()
    assert not app.exception
    assert any('2 puntos' in item.value for item in app.info)
    assert app.dataframe[0].value.equals(table)
    points = prepare_timeline(rows, years=(2025, 2025)).points
    reference = moving_average(points, rows)
    spec = timeline_chart(points, '2025-01-01', '2025-12-01', reference).to_dict()
    assert spec['data']['values'][:24] == points
    assert len(spec['data']['values']) == 26
    assert spec['encoding']['strokeDash']['field'] == 'Serie'
    assert 'strokeWidth' in spec['encoding']
    assert 'transform' not in spec


def test_friendly_table_full_traceability_categories_and_reset(database):
    from src.gui_presentation import short_id
    app = page()
    table = app.dataframe[0].value
    assert 'Observación' not in table and 'Elegibilidad' not in table
    assert table.iloc[0]['Periodo'] == '03/2024'
    assert '…' in table.iloc[0]['Documento']
    assert any('Pagas de beneficios · Sin registros' == label for label in app.multiselect[1].options)
    app.selectbox[1].select(0).run()
    assert not app.exception
    assert short_id(app.code[0].value) == table.iloc[0]['Documento']
    assert any(item.value == 'a' * 64 for item in app.code)
    app.multiselect[1].set_value(['Pagas extraordinarias']).run()
    assert not app.get('vega_lite_chart')
    assert any('No hay puntos' in item.value for item in app.info)
    app.selectbox[0].select('Empresa Beta')
    app.multiselect[0].set_value(['Neto'])
    app.slider[0].set_range(2025, 2025).run()
    assert app.multiselect[1].value == ['Pagas extraordinarias']
    app.button[0].click().run()
    assert app.selectbox[0].value is None
    assert app.multiselect[0].value == ['Bruto', 'Neto']
    assert app.multiselect[1].value == ['Documentos sin clasificar']
    assert not app.checkbox[0].value
    assert len(app.dataframe[0].value) == 10
    assert not app.code


def test_category_chart_has_only_ordinary_lines_and_isolated_markers():
    from src.analytic_dataset import DocumentCategory as C
    from src.payroll_timeline import category_chart, classified_timeline
    from tests.unit.test_payroll_timeline import analytic, record
    rows = [record(doc='one'), record(doc='extra', month=2), record(doc='three', month=3),
            record(doc='benefit', month=4), record(doc='other', month=5)]
    dataset = [analytic('one', C.ORDINARY), analytic('three', C.ORDINARY),
               analytic('extra', C.EXTRA), analytic('benefit', C.BENEFITS), analytic('other', C.OTHER)]
    result = classified_timeline(rows, dataset, years=(2025, 2025))
    spec = category_chart(result.points, '2025-01-01', '2025-05-01', []).to_dict()
    lines, markers, _ = spec['layer']
    assert lines['mark']['type'] == 'line'
    assert {p['Documento'] for p in lines['data']['values']} == {'one', 'three'}
    assert len({p['Tramo'] for p in lines['data']['values']}) == 2
    assert markers['mark']['type'] == 'point'
    assert {p['Documento'] for p in markers['data']['values']} == {'extra', 'benefit', 'other'}
    assert 'transform' not in spec


def test_unclassified_reference_is_omitted_without_changing_points(database, monkeypatch):
    from tests.unit.test_payroll_timeline import year_records
    monkeypatch.setattr('src.canonical_inspection.CanonicalInspector.timeline_records', lambda self: year_records())
    app = page()
    original = app.get('vega_lite_chart')[0].proto.spec
    app.checkbox[0].check().run()
    assert any('0 puntos' in item.value for item in app.info)
    assert any('no disponible' in item.value for item in app.caption)
    assert app.get('vega_lite_chart')[0].proto.spec == original
    assert not app.exception


def test_hiding_categories_does_not_change_average_inputs(database, monkeypatch):
    from src.analytic_dataset import DocumentCategory as C
    from src.payroll_timeline import category_average
    from tests.unit.test_payroll_timeline import analytic, record, year_records
    rows = year_records() + [record('bonus', year=2026, month=1)]
    docs = [analytic(f'd{m}', C.ORDINARY) for m in range(1, 13)] + [analytic('bonus', C.VARIABLE_BONUS)]
    monkeypatch.setattr('src.canonical_inspection.CanonicalInspector.timeline_records', lambda self: rows)
    monkeypatch.setattr('src.payroll_timeline.load_analytic_dataset', lambda path: docs)
    inputs = []
    def capture(points, records, *, classified):
        inputs.append(points)
        return category_average(points, records, classified=classified)
    monkeypatch.setattr('src.payroll_timeline.category_average', capture)
    app = page()
    app.checkbox[0].check().run()
    assert any('2 puntos' in item.value for item in app.info)
    app.multiselect(key='timeline_categories').set_value(['Nóminas ordinarias']).run()
    assert any('2 puntos' in item.value for item in app.info)
    assert inputs[-1] == inputs[-2] and len(inputs[-1]) == 25
    assert not app.exception
