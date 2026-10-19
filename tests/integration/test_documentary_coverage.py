"""Real inspector snapshot and synthetic SQLite; no corpus access or writes on read."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.documentary_coverage import Availability, load_coverage, summarize_coverage
from tests.integration import test_document_explorer as fixtures
from tests.integration.test_payroll_timeline import add_version_or_document

database = fixtures.database
isolated_configuration = fixtures.isolated_configuration


def page():
    return AppTest.from_string('from src.coverage_view import render_coverage\nrender_coverage()').run(timeout=20)


def test_loader_one_snapshot_read_only_and_inspector_vs_analytic(database, monkeypatch):
    import src.documentary_coverage as module
    add_version_or_document(database, False)
    before = database.read_bytes()
    files = set(database.parent.iterdir())
    original = module.open_inspector
    opened = []
    @contextmanager
    def spy(path):
        with original(path) as inspector:
            opened.append(inspector)
            yield inspector
    monkeypatch.setattr(module, 'open_inspector', spy)
    rows = load_coverage(database)
    assert len(opened) == 1
    report = summarize_coverage(rows, years=(2024, 2025))
    assert len(report.document_ids) == 4
    assert len(report.certified_both) == 1
    assert report.analytic_gross == report.analytic_net == ()
    assert report.multiversion_ids == report.certified_both
    value = next(d for d in rows if d.company == 'Empresa Alfa')
    assert value.gross == value.net == Availability.CERTIFIED
    assert all(reason.value != 'observation.ambiguous' for reason in value.review_reasons)
    assert len(value.document.observations) == 2
    assert len(value.document.provenance) == 2
    assert value.document.observation_facts
    assert database.read_bytes() == before and set(database.parent.iterdir()) == files


def test_restriction_preserves_every_record_and_certification(database):
    rows = load_coverage(database)
    identity = next(d.document_id for d in rows if d.gross == Availability.CERTIFIED)
    with_hold = load_coverage(database, withheld_document_ids=(identity,))
    assert tuple(replace(d, presentation_restricted=False) for d in with_hold) == rows
    report = summarize_coverage(with_hold, years=(2024, 2025))
    assert report.restricted_ids == (identity,)
    assert len(report.document_ids) == 4


def test_page_filters_counts_traceability_and_no_writes(database):
    before = database.read_bytes()
    app = page()
    assert not app.exception
    assert app.title[0].value == 'Cobertura documental'
    assert app.metric[0].value == '4'
    assert any('no significa desempleo' in c.value for c in app.caption)
    app.selectbox[0].select('Empresa Alfa').run()
    assert app.metric[0].value == '1'
    assert not app.exception
    app.selectbox[1].select('Bruto · Certificado (inspector)').run()
    assert len(app.dataframe[-1].value) == 1
    ids = [d.document_id for d in load_coverage(database) if d.company == 'Empresa Alfa']
    app.selectbox[2].select(ids[0]).run()
    assert not app.exception
    assert any(c.value == ids[0] for c in app.code)
    assert any(c.value == 'a'*64 for c in app.code)
    app.selectbox[0].select('Empresa Beta').run()
    app.selectbox[1].select('Todos los documentos').run()
    assert app.metric[0].value == '2'
    app.slider[0].set_range(2024, 2024).run()
    assert app.metric[0].value == '0'
    assert database.read_bytes() == before


def test_page_empty_and_missing_database(tmp_path, monkeypatch):
    from src.persistence import open_database
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    assert 'No hay documentos' in page().info[0].value
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(tmp_path / 'missing.sqlite'))
    assert page().error
    assert not (tmp_path / 'missing.sqlite').exists()


def test_navigation_preserves_existing_pages(database):
    app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / 'app.py')).run(timeout=20)
    assert not app.exception
    labels = {getattr(link, 'label', None) for link in app.get('page_link')}
    assert {'Explorador', 'Evolución histórica', 'Cobertura documental'} <= labels


def test_page_shows_hold_separately_without_removing_counts(database, monkeypatch):
    from src.cli_config import load_config
    config = load_config()
    identity = next(d.document_id for d in load_coverage(database) if d.gross == Availability.CERTIFIED)
    monkeypatch.setattr('src.coverage_view.load_config', lambda: replace(config, withheld_document_ids=(identity,)))
    app = page()
    assert not app.exception
    assert app.metric[0].value == '4'
    app.selectbox[1].select('Restricciones locales de presentación').run()
    assert len(app.dataframe[-1].value) == 1
    assert app.dataframe[-1].value.iloc[0]['Restricción de presentación'] == 'Sí'
    assert app.metric[0].value == '4'
