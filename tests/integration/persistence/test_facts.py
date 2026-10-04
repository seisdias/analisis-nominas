"""Atomic documentary facts and honest page provenance, using synthetic data."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest

from src.canonical import (
    CanonicalValue,
    CurrencyCode,
    ExactDecimal,
    ReproducibilityConflict,
    ValueState,
)
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
    Person,
    SourceFile,
    corpus_id,
    person_id,
    source_file_id,
)
from src.canonical.facts import DocumentaryFact, FactDraft, FactPage, fact_id
from src.persistence import (
    Migration,
    MigrationChecksumError,
)
from src.persistence import (
    load_migrations as packaged_migrations,
)
from src.persistence import (
    open_database as packaged_open_database,
)
from src.persistence import (
    verify_schema as packaged_verify_schema,
)
from src.persistence.evidence import EvidenceRepository, WriteOutcome


# V4-specific assertions remain isolated; test_economics.py tests packaged v5.
def load_migrations():
    return packaged_migrations()[:4]


def open_database(path: str | Path, *, mode: Literal['create', 'migrate', 'verify'] = 'verify',
                  **kwargs: Any):
    kwargs.setdefault('migrations', load_migrations())
    return packaged_open_database(path, mode=mode, **kwargs)


def verify_schema(connection):
    return packaged_verify_schema(connection, load_migrations())


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = EvidenceRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'v1')
        file = SourceFile(source_file_id('a'*64), 'a'*64, 1, 'application/pdf', page_count=3)
        doc = LogicalDocument(document_id(corpus.corpus_id, 'unit'), corpus.corpus_id, None, 'unknown', 'unit')
        version = DocumentVersion(version_id(doc.document_id, file.file_id, 'whole'), doc.document_id, file.file_id, 'whole')
        extraction = Extraction(extraction_id(version.version_id, 'synthetic', 'v1', 'b'*64), version.version_id, 'synthetic', 'v1', 'b'*64, 'c'*64)
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(file)
        repo.register_document(doc)
        repo.register_version(version)
        repo.register_extraction(extraction)
        yield repo, db.connection, version, extraction


def make_fact(extraction, value, key='synthetic.value'):
    return DocumentaryFact.from_draft(extraction.extraction_id, FactDraft(key, value))


VALUES = [
    CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(c, 2), currency=currency)
    for c in [0, 20153, -20153] for currency in [None, CurrencyCode('EUR')]
] + [CanonicalValue(state=ValueState.PRESENT, value=text) for text in ['', 'ñ 001', '000.10']] + [
    CanonicalValue(state=state, reason_code='synthetic.reason', currency=CurrencyCode('USD'))
    for state in ValueState if state != ValueState.PRESENT
] + [CanonicalValue(state=ValueState.UNRELIABLE, value=ExactDecimal(-1, 0), reason_code='synthetic.reason'),
     CanonicalValue(state=ValueState.UNRELIABLE, value='candidate', reason_code='synthetic.reason')]


@pytest.mark.parametrize('value', VALUES)
def test_values_states_roundtrip_exact_and_idempotent(store, value):
    repo, _, _, extraction = store
    fact = make_fact(extraction, value)
    assert repo.register_fact(fact) == WriteOutcome.CREATED
    assert repo.register_fact(replace(fact, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_fact(fact.fact_id) == fact
    assert repo.get_extraction_facts(extraction.extraction_id) == (fact,)
    assert not isinstance(repo.get_fact(fact.fact_id), sqlite3.Row)
    assert fact_id(str(extraction.extraction_id), fact.fact_key) == fact.fact_id


def test_same_identity_changed_value_conflicts(store):
    repo, _, _, extraction = store
    fact = make_fact(extraction, VALUES[0])
    repo.register_fact(fact)
    changed = replace(fact, value=VALUES[2])
    assert changed.fact_id == fact.fact_id
    with pytest.raises(ReproducibilityConflict):
        repo.register_fact(changed)
    assert repo.get_fact(fact.fact_id) == fact


def test_pages_none_one_many_and_no_scope_guessing(store):
    repo, _, version, extraction = store
    fact = make_fact(extraction, VALUES[0])
    repo.register_fact(fact)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    repo.associate_page(VersionPage(version.version_id, 3, 1))
    assert repo.get_fact_pages(fact.fact_id) == ()
    first = FactPage(fact.fact_id, 1)
    assert repo.associate_fact_page(first) == WriteOutcome.CREATED
    assert repo.associate_fact_page(first) == WriteOutcome.IDENTICAL
    assert repo.get_fact_pages(fact.fact_id) == (first,)
    third = FactPage(fact.fact_id, 3)
    repo.associate_fact_page(third)
    assert repo.get_fact_pages(fact.fact_id) == (first, third)
    # Page 2 exists physically but was not established in this version's scope.
    with pytest.raises(ValueError):
        repo.associate_fact_page(FactPage(fact.fact_id, 2))


@pytest.mark.parametrize('page', [0, -1, True, 1.5])
def test_invalid_page_contract(page):
    with pytest.raises(ValueError):
        FactPage('fact:sha256:' + 'a'*64, page)


def test_missing_extraction_and_fact_fk(store):
    repo, conn, _, extraction = store
    fact = DocumentaryFact.from_draft('extraction:sha256:' + 'f'*64, FactDraft('key', VALUES[0]))
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_fact(fact)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO fact_pages (fact_id, version_id, page_number) VALUES (?, ?, ?)',
                     (fact.fact_id, extraction.version_id, 1))
    for table in ['documentary_facts', 'fact_pages']:
        rows = conn.execute(f'PRAGMA foreign_key_list({table})').fetchall()
        assert rows and all(r[5:7] == ('RESTRICT', 'RESTRICT') for r in rows)


@pytest.mark.parametrize('table,key', [('extractions', 'extraction_id'), ('documentary_facts', 'fact_id')])
@pytest.mark.parametrize('operation', ['DELETE', 'UPDATE'])
def test_fk_restrict(store, table, key, operation):
    repo, conn, version, extraction = store
    fact = make_fact(extraction, VALUES[0])
    repo.register_fact(fact)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    repo.associate_fact_page(FactPage(fact.fact_id, 1))
    with pytest.raises(sqlite3.IntegrityError):
        if operation == 'DELETE':
            conn.execute(f'DELETE FROM {table}')
        else:
            old = conn.execute(f'SELECT {key} FROM {table}').fetchone()[0]
            conn.execute(f'UPDATE {table} SET {key}=?', (old[:-64] + 'f'*64,))


def test_conflict_rolls_back_facts_and_pages(store):
    repo, conn, version, extraction = store
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    fact = make_fact(extraction, VALUES[0])
    with pytest.raises(ReproducibilityConflict):
        with repo.transaction():
            repo.register_fact(fact)
            repo.associate_fact_page(FactPage(fact.fact_id, 1))
            repo.register_fact(replace(fact, value=VALUES[2]))
    assert repo.get_extraction_facts(extraction.extraction_id) == ()
    assert conn.execute('SELECT count(*) FROM fact_pages').fetchone() == (0,)


@pytest.mark.parametrize('from_v3', [False, True])
def test_schema_v4_upgrade_idempotence_integrity(tmp_path, from_v3):
    path = tmp_path / 'synthetic.sqlite'
    catalog = load_migrations()
    if from_v3:
        with open_database(path, mode='create', migrations=catalog[:3]):
            pass
        with open_database(path) as db:
            assert db.status.pending_versions == (4,)
    with open_database(path, mode='migrate' if from_v3 else 'create') as db:
        assert verify_schema(db.connection).current_version == 4
        tables = {r[0] for r in db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert tables == {'schema_migrations', 'persons', 'employers', 'corpora',
                          'source_files', 'file_locations', 'ingest_runs', 'ingest_items',
                          'logical_documents', 'document_versions', 'version_pages',
                          'extractions', 'documentary_facts', 'fact_pages'}
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        history = db.connection.execute('SELECT * FROM schema_migrations').fetchall()
        assert all(r[2] != 'REAL' for r in db.connection.execute('PRAGMA table_info(documentary_facts)'))
    with open_database(path, mode='migrate') as db:
        assert db.connection.execute('SELECT * FROM schema_migrations').fetchall() == history
    with pytest.raises(MigrationChecksumError):
        with open_database(path, migrations=(*catalog[:3], Migration(4, catalog[3].sql + '\n-- altered'))):
            pass


@pytest.mark.parametrize('assignment', [
    "value_state='present', value_kind=NULL, coefficient=NULL, scale=NULL",
    "value_state='unknown'", "value_state='unreliable', reason_code=NULL",
    "value_kind='text'", 'scale=10', 'coefficient=1.25',
    "currency='eur'", "reason_code='a.1'", "value_kind='invalid'",
])
def test_sql_rejects_contradictory_values(store, assignment):
    repo, conn, _, extraction = store
    repo.register_fact(make_fact(extraction, VALUES[2]))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'UPDATE documentary_facts SET {assignment}')


@pytest.mark.parametrize('coefficient,scale', [(-(2**63), 0), (2**63-1, 9), (1, 9)])
def test_signed_integer_and_precision_boundaries(store, coefficient, scale):
    repo, conn, _, extraction = store
    fact = make_fact(extraction, CanonicalValue(state=ValueState.PRESENT,
                                               value=ExactDecimal(coefficient, scale)))
    repo.register_fact(fact)
    assert repo.get_fact(fact.fact_id) == fact
    assert conn.execute('SELECT typeof(coefficient), typeof(scale) FROM documentary_facts').fetchone() == ('integer', 'integer')


def test_page_provenance_cannot_be_deleted_or_reassigned(store):
    repo, conn, version, extraction = store
    fact = make_fact(extraction, VALUES[0])
    repo.register_fact(fact)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    repo.associate_fact_page(FactPage(fact.fact_id, 1))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('DELETE FROM version_pages')
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('UPDATE version_pages SET page_number=2')


def test_page_from_other_version_is_not_evidence_for_this_fact(store):
    repo, _, version, extraction = store
    other = replace(version, segment_key='other',
                    version_id=version_id(version.document_id, version.file_id, 'other'))
    repo.register_version(other)
    repo.associate_page(VersionPage(other.version_id, 2, 0))
    fact = make_fact(extraction, VALUES[0])
    repo.register_fact(fact)
    with pytest.raises(ValueError):
        repo.associate_fact_page(FactPage(fact.fact_id, 2))


def test_fact_key_and_extraction_define_identity_and_query_order(store):
    repo, _, _, extraction = store
    one = make_fact(extraction, VALUES[0], 'z')
    two = make_fact(extraction, VALUES[0], 'a')
    assert one.fact_id != two.fact_id
    assert fact_id('extraction:sha256:' + 'f'*64, 'z') != one.fact_id
    repo.register_fact(one)
    repo.register_fact(two)
    assert repo.get_extraction_facts(extraction.extraction_id) == (two, one)


def test_adapter_drafts_bind_and_roundtrip_without_pages(store):
    from src.models.nomina import Nomina
    from src.nomina_facts import adapt_nomina

    repo, _, _, extraction = store
    model = Nomina('synthetic', 2020, 1, 'Jan', 'Synthetic', 'TEST', total_devengado=-201.53)
    drafts = adapt_nomina(model)
    bound = tuple(DocumentaryFact.from_draft(extraction.extraction_id, draft,
                                             created_at='2026-01-01T00:00:00Z') for draft in drafts)
    with repo.transaction():
        for fact in bound:
            repo.register_fact(fact)
    assert repo.get_extraction_facts(extraction.extraction_id) == bound
    assert all(repo.get_fact_pages(fact.fact_id) == () for fact in bound)
