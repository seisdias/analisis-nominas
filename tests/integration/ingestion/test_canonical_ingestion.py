"""Synthetic orchestration: one database, physical-PDF transactions, no real corpus."""
from dataclasses import replace
from uuid import UUID

import pytest

from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical.serialization import sha256_bytes
from src.canonical_ingestion import CorpusInput, InputPDF, ingest, inventory
from src.ingestion_processors import OrdinaryPDF, PayrollUnit
from src.models.nomina import Nomina
from src.persistence import open_database
from src.persistence.relations import RelationRepository


def payroll(company='one', identity='one'):
    return Nomina(id=identity, anio=2020, mes=1, periodo='January', empresa=company,
                  cif='SYNTHETIC', total_devengado=100, liquido_percibir=90)


class SyntheticProcessor:
    revision = 'synthetic/v1'

    def __init__(self):
        self.calls = []

    def prepare(self, data, filename):
        self.calls.append(filename)
        if data == b'fail':
            raise ValueError('Sensitive path /private/person.pdf')
        units = [PayrollUnit('first', payroll(data.decode()), (1,))]
        if data == b'multi':
            units.append(PayrollUnit('second', payroll(filename, 'two'), (2,)))
        if data == b'rollback':
            units.append(PayrollUnit('second', replace(payroll(), total_devengado=float('nan')), (2,)))
        return OrdinaryPDF(2, tuple(units), self.revision, 'synthetic')


@pytest.fixture
def store(tmp_path):
    with open_database(':memory:', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(UUID(int=1)), 'synthetic')
        repo.register_person(person)
        bindings = []
        for i in (2, 3):
            corpus = Corpus(corpus_id(UUID(int=i)), person.person_id, str(i), 'v1')
            repo.register_corpus(corpus)
            root = tmp_path/str(i)
            root.mkdir()
            bindings.append(CorpusInput(corpus.corpus_id, root, 'synthetic'))
        yield repo, db.connection, bindings


def test_two_companies_one_database_and_no_repeat_work(store):
    repo, conn, bindings = store
    for i, binding in enumerate(bindings):
        (binding.root/'pay.pdf').write_bytes(f'company{i}'.encode())
    processor = SyntheticProcessor()
    result = ingest(repo, bindings, {'synthetic': processor})
    assert (result.processed, result.failed, result.skipped) == (2, 0, 0)
    assert conn.execute('SELECT count(*) FROM logical_documents').fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 4
    assert {r[0] for r in conn.execute('SELECT eligibility FROM economic_observations')} == {'evidence_only'}
    before = tuple(conn.iterdump())
    again = ingest(repo, list(reversed(bindings)), {'synthetic': processor})
    assert again == result
    assert len(processor.calls) == 2
    assert tuple(conn.iterdump()) == before
    assert conn.execute('SELECT count(*) FROM ingest_runs').fetchone()[0] == 1


def test_order_is_corpus_hash_path_not_input_order(store):
    repo, _, bindings = store
    for binding in bindings:
        for name, data in [('z.pdf', b'one'), ('a.pdf', b'two')]:
            (binding.root/name).write_bytes(data)
    sources = inventory(bindings)
    processor = SyntheticProcessor()
    ingest(repo, bindings, {'synthetic': processor}, sources=tuple(reversed(sources)))
    assert processor.calls == [s.relative_path for s in sorted(sources, key=lambda s: (s.corpus_id, s.sha256, s.relative_path))]


def test_multipage_units_commit_together_and_preserve_provenance(store):
    repo, conn, bindings = store
    (bindings[0].root/'multi.pdf').write_bytes(b'multi')
    result = ingest(repo, bindings, {'synthetic': SyntheticProcessor()})
    assert result.processed == 1
    assert conn.execute('SELECT count(*) FROM document_versions').fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM fact_pages').fetchone()[0] > 0
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('failure', [b'fail', b'rollback'])
def test_failure_continues_and_rolls_back_all_pdf_artifacts(store, failure):
    repo, conn, bindings = store
    (bindings[0].root/'bad.pdf').write_bytes(failure)
    (bindings[0].root/'good.pdf').write_bytes(b'ok')
    processor = SyntheticProcessor()
    result = ingest(repo, bindings, {'synthetic': processor})
    assert (result.processed, result.failed) == (1, 1)
    for table in ('source_files', 'logical_documents', 'document_versions', 'extractions', 'assessments'):
        assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 1
    assert conn.execute("SELECT error_detail FROM ingest_items WHERE status='failed'").fetchone()[0] == 'Details omitted; see reason_code.'
    assert repo.get_run(result.run_id).status == 'partial'
    before = tuple(conn.iterdump())
    assert ingest(repo, bindings, {'synthetic': processor}) == result
    assert len(processor.calls) == 2
    assert tuple(conn.iterdump()) == before


def test_input_hash_change_fails_before_parser(store):
    repo, _, bindings = store
    path = bindings[0].root/'pay.pdf'
    path.write_bytes(b'original')
    sources = inventory(bindings)
    path.write_bytes(b'changed')
    processor = SyntheticProcessor()
    result = ingest(repo, bindings, {'synthetic': processor}, sources=sources)
    assert result.failed == 1 and not processor.calls


def test_explicit_skip_is_in_inventory_and_never_parsed(store):
    repo, conn, bindings = store
    (bindings[0].root/'certificate.pdf').write_bytes(b'certificate')
    sources = tuple(replace(s, skip_reason='annual_certificate') for s in inventory(bindings))
    processor = SyntheticProcessor()
    result = ingest(repo, bindings, {'synthetic': processor}, sources=sources)
    assert result.skipped == 1 and not processor.calls
    assert conn.execute('SELECT count(*) FROM source_files').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM logical_documents').fetchone()[0] == 0


def test_invalid_paths_rejected():
    with pytest.raises(ValueError):
        InputPDF(corpus_id(), '../outside.pdf', 'a'*64, 'synthetic')


def test_missing_file_records_failure_and_continues(store):
    repo, _, bindings = store
    item = InputPDF(bindings[0].corpus_id, 'missing.pdf', sha256_bytes(b'none'), 'synthetic')
    assert ingest(repo, bindings, {'synthetic': SyntheticProcessor()}, sources=(item,)).failed == 1


def test_completed_input_changed_is_not_silently_skipped(store):
    from src.canonical import ReproducibilityConflict

    repo, conn, bindings = store
    path = bindings[0].root/'pay.pdf'
    path.write_bytes(b'ok')
    sources = inventory(bindings)
    processor = SyntheticProcessor()
    ingest(repo, bindings, {'synthetic': processor}, sources=sources)
    before = tuple(conn.iterdump())
    path.write_bytes(b'changed')
    with pytest.raises(ReproducibilityConflict):
        ingest(repo, bindings, {'synthetic': processor}, sources=sources)
    assert tuple(conn.iterdump()) == before
    assert len(processor.calls) == 1


def test_alten_documentary_path_reuses_certified_bridge(store):
    from src.candidate_selection import select_candidates
    from src.ingestion_processors import AltenPDF
    from tests.integration.persistence.test_alten_canonical import legacy

    repo, conn, bindings = store
    data = b'alten synthetic'
    (bindings[0].root/'alten.pdf').write_bytes(data)
    digest = sha256_bytes(data)
    p, a = legacy(digest, 1)
    _, b = legacy(digest, 2, 200)

    class Processor:
        revision = 'synthetic-alten/v1'

        def prepare(self, data, filename):
            return AltenPDF(2, (p,), (a, b))

    result = ingest(repo, bindings, {'synthetic': Processor()})
    assert result.processed == 1 and result.failed == 0
    assert conn.execute('SELECT count(*) FROM logical_documents').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM document_versions').fetchone()[0] == 2
    assert {a.status for a in repo.list_assessments()} == {'ambiguous'}
    assert not select_candidates(repo).candidates
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0


def test_unknown_scope_does_not_invent_fact_pages(store):
    repo, conn, bindings = store
    (bindings[0].root/'wide.pdf').write_bytes(b'wide')

    class Processor:
        revision = 'wide/v1'

        def prepare(self, data, filename):
            return OrdinaryPDF(2, (PayrollUnit('whole', payroll(), (1, 2)),), self.revision, 'synthetic')

    assert ingest(repo, bindings, {'synthetic': Processor()}).processed == 1
    assert conn.execute('SELECT count(*) FROM version_pages').fetchone()[0] == 2
    assert conn.execute('SELECT count(*) FROM fact_pages').fetchone()[0] == 0


def test_duplicate_segments_roll_back(store):
    repo, conn, bindings = store
    (bindings[0].root/'bad.pdf').write_bytes(b'duplicate')

    class Processor:
        revision = 'duplicate/v1'

        def prepare(self, data, filename):
            unit = PayrollUnit('same', payroll(), (1,))
            return OrdinaryPDF(1, (unit, unit), self.revision, 'synthetic')

    assert ingest(repo, bindings, {'synthetic': Processor()}).failed == 1
    assert conn.execute('SELECT count(*) FROM documentary_facts').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM source_files').fetchone()[0] == 0


def test_symlink_cannot_escape_corpus(store, tmp_path):
    _, _, bindings = store
    outside = tmp_path/'outside.pdf'
    outside.write_bytes(b'private')
    (bindings[0].root/'link.pdf').symlink_to(outside)
    with pytest.raises(ValueError):
        inventory(bindings)


def test_uncertain_totals_not_promoted(store):
    repo, conn, bindings = store
    (bindings[0].root/'zero.pdf').write_bytes(b'zero')

    class Processor:
        revision = 'zero/v1'

        def prepare(self, data, filename):
            return OrdinaryPDF(1, (PayrollUnit('whole', replace(payroll(), total_devengado=0), (1,)),), self.revision, 'synthetic')

    assert ingest(repo, bindings, {'synthetic': Processor()}).processed == 1
    assert {a.status for a in repo.list_assessments()} == {'pending'}
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0


@pytest.mark.parametrize('company', ['coritel', 'insis', 'ineco', 'exceltic', 'altran'])
def test_ordinary_binding_calls_existing_extractor_parser_adapter(company, monkeypatch):
    import src.ingestion_processors as module
    from src.extraction import ExtractedDocument
    from src.parsers.parser_factory import ParserFactory

    parser = ParserFactory().obtener_parser(company)
    processor = module.OrdinaryProcessor(parser)
    extracted = ExtractedDocument('synthetic', pages=(ExtractedDocument('synthetic'),))
    calls = []
    monkeypatch.setattr(module, 'extract_pdf_document', lambda stream: extracted)
    def parse(document, filename):
        calls.append((document, filename))
        return payroll(company)
    monkeypatch.setattr(parser, 'parse_extracted', parse)
    prepared = processor.prepare(b'pdf', 'physical.pdf')
    assert calls == [(extracted, 'physical.pdf')]
    assert prepared.units[0].model.empresa == company
    assert prepared.units[0].pages == (1,)


def test_ordinary_binding_rejects_alten():
    from src.ingestion_processors import OrdinaryProcessor
    from src.parsers.alten_parser import AltenParser
    with pytest.raises(ValueError):
        OrdinaryProcessor(AltenParser())


def test_scanned_binding_omits_without_parser(monkeypatch):
    import src.ingestion_processors as module
    from src.extraction import ExtractedDocument
    from src.parsers.coritel_parser import CoritelParser
    processor = module.OrdinaryProcessor(CoritelParser())
    monkeypatch.setattr(module, 'extract_pdf_document', lambda stream: ExtractedDocument('', pages=(ExtractedDocument(''),)))
    result = processor.prepare(b'pdf', 'scan.pdf')
    assert result.skip_reason == 'no_extractable_text' and result.page_count == 1
