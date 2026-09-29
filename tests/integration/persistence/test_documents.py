"""Document provenance on synthetic SQLite, without parsing or economic facts."""

import sqlite3
from dataclasses import replace

import pytest

from src.canonical import ReproducibilityConflict, canonical_sha256, sha256_bytes
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    VersionPage,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.evidence import (
    Corpus,
    Employer,
    Person,
    SourceFile,
    corpus_id,
    employer_id,
    person_id,
    source_file_id,
)
from src.persistence import (
    Migration,
    MigrationChecksumError,
    load_migrations,
    open_database,
    verify_schema,
)
from src.persistence.evidence import EvidenceRepository, WriteOutcome


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = EvidenceRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'manifest/v1')
        employer = Employer(employer_id('ES', 'SYNTHETIC'), 'ES', 'SYNTHETIC', 'Synthetic')
        digest = sha256_bytes(b'synthetic multi-document PDF')
        file = SourceFile(source_file_id(digest), digest, 28, 'application/pdf', page_count=5)
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_employer(employer)
        repo.register_source_file(file)
        yield repo, db.connection, corpus, employer, file


def chain(store):
    repo, _, corpus, employer, file = store
    doc = LogicalDocument(document_id(corpus.corpus_id, 'manifest/unit-1'),
                          corpus.corpus_id, employer.employer_id, 'payroll', 'manifest/unit-1')
    version = DocumentVersion(version_id(doc.document_id, file.file_id, 'segment-1'),
                              doc.document_id, file.file_id, 'segment-1')
    repo.register_document(doc)
    repo.register_version(version)
    return doc, version


def extraction(version, revision='revision-1', config=None):
    config_hash = canonical_sha256(config)
    return Extraction(extraction_id(version.version_id, 'synthetic', revision, config_hash),
                      version.version_id, 'synthetic', revision, config_hash, sha256_bytes(b'output'))


def test_document_idempotent_and_conflicting(store):
    repo, _, _, _, _ = store
    doc, _ = chain(store)
    assert document_id(doc.corpus_id, doc.origin_key) == doc.document_id
    assert repo.register_document(replace(doc, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_document(doc.document_id) == doc
    with pytest.raises(ReproducibilityConflict):
        repo.register_document(replace(doc, document_type='certificate'))
    assert repo.get_document(doc.document_id) == doc


def test_distinct_documents_same_employer_and_period_coexist(store):
    # Period is source context only, not a unique key or economic interpretation.
    repo, conn, corpus, employer, _ = store
    source_units = [('2020-06', 'ordinary-unit'), ('2020-06', 'extra-unit')]
    docs = [LogicalDocument(document_id(corpus.corpus_id, key), corpus.corpus_id,
                            employer.employer_id, 'payroll', key) for _, key in source_units]
    assert source_units[0][0] == source_units[1][0]
    for doc in docs:
        assert repo.register_document(doc) == WriteOutcome.CREATED
    assert docs[0].document_id != docs[1].document_id
    assert conn.execute('SELECT count(*) FROM logical_documents').fetchone() == (2,)


@pytest.mark.parametrize('missing', ['corpus', 'employer'])
def test_document_foreign_keys(store, missing):
    repo, _, corpus, employer, _ = store
    corpus_key = corpus_id() if missing == 'corpus' else corpus.corpus_id
    employer_key = employer_id('ES', 'MISSING') if missing == 'employer' else employer.employer_id
    doc = LogicalDocument(document_id(corpus_key, 'unit'), corpus_key, employer_key, 'unknown', 'unit')
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_document(doc)


def test_optional_employer_and_corpus_scoped_identity(store):
    repo, _, corpus, _, _ = store
    doc = LogicalDocument(document_id(corpus.corpus_id, 'unit'), corpus.corpus_id, None, 'unknown', 'unit')
    assert repo.register_document(doc) == WriteOutcome.CREATED
    assert repo.get_document(doc.document_id) == doc
    assert document_id(corpus_id(), 'unit') != doc.document_id


def test_versions_pdf_sharing_and_segments(store):
    repo, conn, corpus, employer, file = store
    doc, version = chain(store)
    assert repo.register_version(replace(version, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_version(version.version_id) == version
    other_segment = replace(version, version_id=version_id(doc.document_id, file.file_id, 'segment-2'),
                            segment_key='segment-2')
    repo.register_version(other_segment)
    digest = sha256_bytes(b'another PDF')
    other_file = replace(file, file_id=source_file_id(digest), sha256=digest)
    repo.register_source_file(other_file)
    repo.register_version(replace(version, file_id=other_file.file_id,
                                  version_id=version_id(doc.document_id, other_file.file_id, 'segment-1')))
    second = LogicalDocument(document_id(corpus.corpus_id, 'unit-2'), corpus.corpus_id,
                             employer.employer_id, 'payroll', 'unit-2')
    repo.register_document(second)
    repo.register_version(DocumentVersion(version_id(second.document_id, file.file_id, 'segment-3'),
                                           second.document_id, file.file_id, 'segment-3'))
    assert conn.execute('SELECT count(*) FROM document_versions').fetchone() == (4,)


def test_pages_order_unknown_and_conflicts(store):
    repo, _, _, _, _ = store
    _, version = chain(store)
    assert repo.get_version_pages(version.version_id) == ()  # No fabricated page 1.
    pages = (VersionPage(version.version_id, 4, 0), VersionPage(version.version_id, 2, 1))
    assert repo.associate_page(pages[1]) == WriteOutcome.CREATED
    assert repo.associate_page(pages[0]) == WriteOutcome.CREATED
    assert repo.associate_page(pages[0]) == WriteOutcome.IDENTICAL
    assert repo.get_version_pages(version.version_id) == pages
    with pytest.raises(ReproducibilityConflict):
        repo.associate_page(replace(pages[0], page_number=3))
    with pytest.raises(ReproducibilityConflict):
        repo.associate_page(replace(pages[0], ordinal=2))
    assert repo.get_version_pages(version.version_id) == pages


@pytest.mark.parametrize(('page', 'ordinal'), [(0, 0), (-1, 0), (1, -1), (True, 0), (1, True), (1.5, 0)])
def test_invalid_pages(page, ordinal):
    with pytest.raises(ValueError):
        VersionPage('version:sha256:' + 'a'*64, page, ordinal)


def test_page_exceeds_known_file_extent(store):
    repo, _, _, _, _ = store
    _, version = chain(store)
    with pytest.raises(ValueError):
        repo.associate_page(VersionPage(version.version_id, 6, 0))
    assert repo.get_version_pages(version.version_id) == ()


def test_extraction_determinism_idempotence_and_output_conflict(store):
    repo, _, _, _, _ = store
    _, version = chain(store)
    result = extraction(version)
    assert result.extraction_id == extraction(version).extraction_id
    assert repo.register_extraction(result) == WriteOutcome.CREATED
    assert repo.register_extraction(replace(result, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_extraction(result.extraction_id) == result
    assert not isinstance(repo.get_extraction(result.extraction_id), sqlite3.Row)
    with pytest.raises(ReproducibilityConflict):
        repo.register_extraction(replace(result, content_hash=sha256_bytes(b'different output')))
    assert repo.get_extraction(result.extraction_id) == result
    for other in [extraction(version, revision='revision-2'), extraction(version, config={'option': True})]:
        assert other.extraction_id != result.extraction_id
        assert repo.register_extraction(other) == WriteOutcome.CREATED


@pytest.mark.parametrize('entity', ['version_document', 'version_file', 'page', 'extraction'])
def test_missing_parent_rejected(store, entity):
    repo, _, _, _, file = store
    doc, version = chain(store)
    absent_version = 'version:sha256:' + 'f'*64
    with pytest.raises(sqlite3.IntegrityError):
        if entity == 'version_document':
            doc_key = 'document:sha256:' + 'f'*64
            repo.register_version(DocumentVersion(version_id(doc_key, file.file_id, 's'), doc_key, file.file_id, 's'))
        elif entity == 'version_file':
            file_key = source_file_id('f'*64)
            repo.register_version(DocumentVersion(version_id(doc.document_id, file_key, 's'), doc.document_id, file_key, 's'))
        elif entity == 'page':
            repo.associate_page(VersionPage(absent_version, 1, 0))
        else:
            result = extraction(version)
            repo.register_extraction(replace(result, version_id=absent_version,
                extraction_id=extraction_id(absent_version, result.extractor_name, result.extractor_revision, result.config_hash)))


@pytest.mark.parametrize('table', ['logical_documents', 'document_versions', 'version_pages', 'extractions'])
def test_fk_restrict_policy(store, table):
    _, conn, _, _, _ = store
    rows = conn.execute(f'PRAGMA foreign_key_list({table})').fetchall()
    assert rows and all(r[5:7] == ('RESTRICT', 'RESTRICT') for r in rows)


@pytest.mark.parametrize('table,key', [('corpora', 'corpus_id'), ('employers', 'employer_id'),
                                      ('source_files', 'file_id'), ('logical_documents', 'document_id'),
                                      ('document_versions', 'version_id')])
@pytest.mark.parametrize('operation', ['DELETE', 'UPDATE'])
def test_parent_delete_and_update_rejected(store, table, key, operation):
    repo, conn, _, _, _ = store
    _, version = chain(store)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    repo.register_extraction(extraction(version))
    with pytest.raises(sqlite3.IntegrityError):
        if operation == 'DELETE':
            conn.execute(f'DELETE FROM {table}')
        else:
            old = conn.execute(f'SELECT {key} FROM {table}').fetchone()[0]
            conn.execute(f'UPDATE {table} SET {key}=?', (old[:-64] + 'f'*64,))


def test_compound_conflict_rolls_back_chain(store):
    repo, conn, _, _, _ = store
    with pytest.raises(ReproducibilityConflict):
        with repo.transaction():
            _, version = chain(store)
            repo.associate_page(VersionPage(version.version_id, 1, 0))
            result = extraction(version)
            repo.register_extraction(result)
            repo.register_extraction(replace(result, content_hash='f'*64))
    for table in ['logical_documents', 'document_versions', 'version_pages', 'extractions']:
        assert conn.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,)


@pytest.mark.parametrize('from_v2', [False, True])
def test_schema_v3_upgrade_reopen_integrity_and_checksum(tmp_path, from_v2):
    path = tmp_path / 'synthetic.sqlite'
    migrations = load_migrations()
    if from_v2:
        with open_database(path, mode='create', migrations=migrations[:2]) as db:
            person = Person(person_id(), 'preserved')
            EvidenceRepository(db.connection).register_person(person)
        with open_database(path) as db:
            assert db.status.current_version == 2
            assert db.status.pending_versions == (3,)
    with open_database(path, mode='migrate' if from_v2 else 'create') as db:
        assert verify_schema(db.connection).current_version == 3
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        expected = {'schema_migrations', 'persons', 'employers', 'corpora', 'source_files',
                    'file_locations', 'ingest_runs', 'ingest_items', 'logical_documents',
                    'document_versions', 'version_pages', 'extractions'}
        assert {r[0] for r in db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")} == expected
        history = db.connection.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall()
        if from_v2:
            assert EvidenceRepository(db.connection).get_person(person.person_id) == person
    with open_database(path, mode='migrate') as db:
        assert db.connection.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall() == history
    with open_database(path) as db:
        assert db.status.current_version == 3
        assert db.status.pending_versions == ()
    with pytest.raises(MigrationChecksumError):
        with open_database(path, migrations=(*migrations[:2], Migration(3, migrations[2].sql + '\n-- changed'))):
            pass


def test_ids_identical_before_and_after_string_roundtrip(store):
    _, _, _, _, file = store
    doc, version = chain(store)
    assert document_id(str(doc.corpus_id), doc.origin_key) == doc.document_id
    assert version_id(str(doc.document_id), str(file.file_id), version.segment_key) == version.version_id
    result = extraction(version)
    assert extraction_id(str(version.version_id), result.extractor_name,
                         result.extractor_revision, result.config_hash) == result.extraction_id
    assert extraction_id(version.version_id, 'other-extractor', result.extractor_revision,
                         result.config_hash) != result.extraction_id


@pytest.mark.parametrize('field,value', [('document_type', ''), ('origin_key', '  '),
                                        ('document_id', 'document:sha256:' + 'f'*64),
                                        ('employer_id', 'invalid'), ('created_at', '2026-01-01')])
def test_invalid_document_contract(store, field, value):
    doc, _ = chain(store)
    with pytest.raises(ValueError):
        replace(doc, **{field: value})


@pytest.mark.parametrize('field,value', [('segment_key', ''), ('segment_key', 'changed'),
                                        ('version_id', 'version:sha256:' + 'f'*64)])
def test_invalid_version_contract(store, field, value):
    _, version = chain(store)
    with pytest.raises(ValueError):
        replace(version, **{field: value})


@pytest.mark.parametrize('field,value', [('extractor_name', ''), ('extractor_revision', ''),
                                        ('config_hash', 'invalid'), ('content_hash', 'F'*64),
                                        ('extraction_id', 'extraction:sha256:' + 'f'*64)])
def test_invalid_extraction_contract(store, field, value):
    _, version = chain(store)
    with pytest.raises(ValueError):
        replace(extraction(version), **{field: value})


@pytest.mark.parametrize('assignment', ['page_number=0', 'ordinal=-1', 'page_number=1.5'])
def test_sql_page_constraints(store, assignment):
    repo, conn, _, _, _ = store
    _, version = chain(store)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'UPDATE version_pages SET {assignment}')


def test_pages_with_unknown_file_extent_are_explicit_evidence(store):
    repo, _, _, _, file = store
    doc, _ = chain(store)
    digest = sha256_bytes(b'unknown page count')
    unknown_extent = replace(file, file_id=source_file_id(digest), sha256=digest, page_count=None)
    repo.register_source_file(unknown_extent)
    version = DocumentVersion(version_id(doc.document_id, unknown_extent.file_id, 'whole'),
                              doc.document_id, unknown_extent.file_id, 'whole')
    repo.register_version(version)
    # The caller supplies this known page, not a guess from a missing page count.
    page = VersionPage(version.version_id, 7, 0)
    assert repo.associate_page(page) == WriteOutcome.CREATED
    assert repo.get_version_pages(version.version_id) == (page,)


def test_persisted_chain_roundtrip_across_reopen(tmp_path):
    path = tmp_path / 'chain.sqlite'
    with open_database(path, mode='create') as db:
        repo = EvidenceRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'manifest/v1')
        digest = sha256_bytes(b'synthetic')
        file = SourceFile(source_file_id(digest), digest, 9, 'application/pdf')
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(file)
        doc = LogicalDocument(document_id(corpus.corpus_id, 'unit'), corpus.corpus_id, None, 'unknown', 'unit')
        version = DocumentVersion(version_id(doc.document_id, file.file_id, 'whole'), doc.document_id, file.file_id, 'whole')
        result = extraction(version)
        page = VersionPage(version.version_id, 1, 0)
        repo.register_document(doc)
        repo.register_version(version)
        repo.associate_page(page)
        repo.register_extraction(result)
    with open_database(path) as db:
        repo = EvidenceRepository(db.connection)
        assert repo.get_document(doc.document_id) == doc
        assert repo.get_version(version.version_id) == version
        assert repo.get_version_pages(version.version_id) == (page,)
        assert repo.get_extraction(result.extraction_id) == result
