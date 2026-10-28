"""Native concept reading with synthetic persistence; no private fixtures."""
import sqlite3

from streamlit.testing.v1 import AppTest

from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    VersionPage,
    extraction_id,
    version_id,
)
from src.canonical.facts import FactPage
from src.canonical_inspection import open_inspector
from src.document_concepts import load_document_concepts
from src.persistence.economics import EconomicRepository
from tests.integration import test_document_explorer as fixtures
from tests.integration.test_analysis_panel import page
from tests.unit.test_document_concepts import fact

isolated_configuration = fixtures.isolated_configuration
database = fixtures.database


def add_concepts(database, *, multiple=False, empty_version=False, many=False):
    with open_inspector(database) as inspector:
        identity = inspector.documents(company='Empresa Alfa')[0]['document_id']
        detail = inspector.document(identity)
    original = detail['versions'][0]['version']
    ext = detail['versions'][0]['extractions'][0]
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute("UPDATE logical_documents SET document_type='NOMINA_ORDINARIA' WHERE document_id=?", (identity,))
        repo = EconomicRepository(db)
        versions = [original]
        if multiple or empty_version:
            other = DocumentVersion(version_id(identity, original.file_id, 'alternative'),
                                    identity, original.file_id, 'alternative')
            repo.register_version(other)
            versions.append(other)
        for v in versions:
            if v != original and empty_version:
                continue
            e = ext if v == original else Extraction(extraction_id(v.version_id,'synthetic','1','b'*64),
                                                       v.version_id,'synthetic','1','b'*64,'c'*64)
            repo.register_extraction(e)
            repo.associate_page(VersionPage(v.version_id, 1, 0))
            for k, value in [('conceptos/0/concepto','Bono'),('conceptos/0/categoria','bono'),
                             ('conceptos/0/columna','devengos'),('conceptos/0/importe',12345),
                             ('conceptos/1/concepto','IRPF'),('conceptos/1/columna','deducciones'),
                             ('conceptos/1/importe',1234),('irpf_importe',1234),
                             ('prorrata_pagas_extra',4567)]:
                f = fact('payload/'+k,value,ext=e.extraction_id)
                repo.register_fact(f)
                repo.associate_fact_page(FactPage(f.fact_id,1))
            if many:
                for i in range(1001):
                    repo.register_fact(fact(f'opaque/{i}', 'technical',ext=e.extraction_id))
    return identity, tuple(v.version_id for v in versions)


def standalone(database, identity):
    return AppTest.from_string(
        'from pathlib import Path\nfrom src.concepts_view import render_concepts\n'
        f'render_concepts(Path({str(database)!r}), {identity!r})').run(timeout=30)


def test_reader_complete_scope_pages_and_read_only(database):
    identity, versions = add_concepts(database,many=True)
    before = database.read_bytes()
    result = load_document_concepts(database,identity)
    assert result.version_ids == versions
    extraction = result.extractions[0]
    assert len(extraction.facts) > 1000
    assert len(extraction.concepts) == 2
    assert all(e.pages == (1,) for c in extraction.concepts for _,e in c.attributes)
    assert load_document_concepts(database,identity) == result
    assert database.read_bytes() == before


def test_single_version_groups_scalars_and_trace(database):
    identity, _ = add_concepts(database)
    before = database.read_bytes()
    app = standalone(database,identity)
    assert not app.exception
    assert not app.selectbox
    labels = [m.value for m in app.markdown]
    assert '**Devengos**' in labels and '**Deducciones**' in labels
    assert any('Bono' in str(d.value) for d in app.dataframe)
    assert any('Prorrata de extras' in str(d.value) for d in app.dataframe)
    assert any('Páginas del hecho' in d.value.columns for d in app.dataframe)
    assert any(identity in c.value for c in app.code)
    assert database.read_bytes() == before


def test_versions_need_explicit_choice_and_never_persist(database):
    identity, versions = add_concepts(database,multiple=True)
    before = database.read_bytes()
    app = standalone(database,identity)
    assert app.selectbox[0].value is None
    assert not any(m.value=='**Devengos**' for m in app.markdown)
    for version in versions:
        app.selectbox[0].select(version).run()
        assert any(m.value=='**Devengos**' for m in app.markdown)
        assert not app.exception
        assert app.selectbox[0].value==version
    assert database.read_bytes() == before


def test_empty_alternative_still_requires_explicit_version(database):
    identity, versions=add_concepts(database,empty_version=True)
    app=standalone(database,identity)
    assert app.selectbox[0].value is None
    app.selectbox[0].select(versions[1]).run()
    assert any('no está disponible' in m.value for m in app.info)
    assert not app.exception


def test_panel_keeps_totals_classification_and_navigation(database):
    identity, _ = add_concepts(database)
    before=database.read_bytes()
    app=page()
    app.text_input(key='panel_period').set_value('03/2024').run()
    app.selectbox(key='panel_document').select(identity).run()
    assert not app.exception
    assert any(h.value=='Desglose documental de conceptos' for h in app.subheader)
    assert any('NOMINA_ORDINARIA' in m.value for m in app.markdown)
    assert any('1.234,56 €' in str(d.value) for d in app.dataframe)
    app.button(key='panel_back').click().run()
    assert app.text_input(key='panel_period').value=='03/2024'
    assert app.selectbox(key='panel_document').value is None
    assert database.read_bytes()==before


def test_scalar_only_does_not_make_empty_document(database):
    with open_inspector(database) as i:
        identity=i.documents(company='Empresa Alfa')[0]['document_id']
        ext=i.document(identity)['versions'][0]['extractions'][0].extraction_id
    with sqlite3.connect(database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        EconomicRepository(db).register_fact(fact('nomina.salario_base',12345,ext=ext))
    app=standalone(database,identity)
    assert any('no está disponible' in i.value for i in app.info)
    assert any('Salario base' in str(d.value) for d in app.dataframe)
    assert not app.exception


def test_panel_multiversion_selection_never_changes_certified_summary(database):
    identity,versions=add_concepts(database,multiple=True)
    app=page()
    app.selectbox(key='panel_document').select(identity).run()
    def totals():
        return next(d.value for d in app.dataframe if 'Bruto documental' in d.value.columns)
    initial=totals().copy()
    key='concept-version-'+identity
    assert app.selectbox(key=key).value is None
    for version in versions:
        app.selectbox(key=key).select(version).run()
        assert totals().equals(initial)
        assert not app.exception


def test_missing_inspector_records_raise_instead_of_empty_evidence(database):
    import pytest

    from src.canonical_inspection import InspectionError
    with open_inspector(database) as i:
        with pytest.raises(InspectionError):
            i.extraction_facts('absent')
        with pytest.raises(InspectionError):
            i.fact_pages('absent')
