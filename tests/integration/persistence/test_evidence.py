"""Canonical identity/evidence on synthetic temporary SQLite only."""
from dataclasses import replace

import pytest

from src.canonical import ReproducibilityConflict, sha256_bytes
from src.canonical.evidence import (
    Corpus,
    Employer,
    FileLocation,
    IngestItem,
    IngestRun,
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
        yield EvidenceRepository(db.connection), db.connection


def records():
    person = Person(person_id(), 'local')
    corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'manifest/v1')
    sha = sha256_bytes(b'abc')
    file = SourceFile(source_file_id(sha), sha, 3, 'application/pdf')
    return person, corpus, file


def test_person_roundtrip_idempotence_and_conflict(store):
    repo, conn = store
    person, _, _ = records()
    assert repo.register_person(person) == WriteOutcome.CREATED
    assert repo.register_person(replace(person, created_at='2030-01-01T00:00:00+00:00')) == WriteOutcome.IDENTICAL
    assert repo.get_person(person.person_id) == person
    with pytest.raises(ReproducibilityConflict):
        repo.register_person(replace(person, local_alias='changed'))
    repo.register_person(Person(person_id(), 'another'))
    assert conn.execute('SELECT count(*) FROM persons').fetchone()[0] == 2


def test_employer_and_corpus_roundtrip(store):
    repo, _ = store
    person, corpus, _ = records()
    repo.register_person(person)
    employer = Employer(employer_id('ES', 'A123'), 'ES', 'A123', 'Company')
    assert repo.register_employer(employer) == WriteOutcome.CREATED
    assert repo.register_employer(employer) == WriteOutcome.IDENTICAL
    assert repo.get_employer(employer.employer_id) == employer
    with pytest.raises(ReproducibilityConflict):
        repo.register_employer(replace(employer, display_name='Different'))
    repo.register_employer(Employer(employer_id('ES'), 'ES', None, 'Company'))
    repo.register_corpus(corpus)
    assert repo.register_corpus(corpus) == WriteOutcome.IDENTICAL
    assert repo.get_corpus(corpus.corpus_id) == corpus
    repo.register_corpus(replace(corpus, corpus_id=corpus_id()))


def test_files_locations_and_conflicting_metadata(store):
    repo, conn = store
    person, corpus, file = records()
    repo.register_person(person)
    repo.register_corpus(corpus)
    assert repo.register_source_file(file) == WriteOutcome.CREATED
    assert repo.register_source_file(file) == WriteOutcome.IDENTICAL
    assert repo.get_source_file(file.file_id) == file
    location = FileLocation(corpus.corpus_id, 'a.pdf', file.file_id, 'a.pdf')
    assert repo.register_location(location) == WriteOutcome.CREATED
    assert repo.register_location(replace(location, first_seen_at='2030-01-01T00:00:00+00:00')) == WriteOutcome.IDENTICAL
    assert repo.get_location(corpus.corpus_id, 'a.pdf', file.file_id) == location
    repo.register_location(replace(location, relative_path='copy.pdf'))
    sha = sha256_bytes(b'changed')
    other = replace(file, file_id=source_file_id(sha), sha256=sha, byte_size=7)
    repo.register_source_file(other)
    repo.register_location(replace(location, file_id=other.file_id))
    assert conn.execute('SELECT count(*) FROM file_locations').fetchone()[0] == 3
    with pytest.raises(ReproducibilityConflict):
        repo.register_source_file(replace(file, byte_size=4))


def test_inventory_and_explicit_updates(store):
    repo, _ = store
    person, corpus, file = records()
    repo.register_person(person)
    repo.register_corpus(corpus)
    repo.register_source_file(file)
    run = IngestRun.from_plan({'files': ['a.pdf']})
    assert repo.create_run(run) == WriteOutcome.CREATED
    assert repo.create_run(IngestRun.from_plan({'files': ['a.pdf']})) == WriteOutcome.IDENTICAL
    assert repo.get_run(run.run_id) == run
    item = IngestItem(run.run_id, 'a', corpus.corpus_id, 'a.pdf', expected_sha256=file.sha256)
    assert repo.register_item(item) == WriteOutcome.CREATED
    assert repo.register_item(item) == WriteOutcome.IDENTICAL
    assert repo.get_item(run.run_id, 'a') == item
    assert repo.update_item(replace(item, status='processed', file_id=file.file_id)) == WriteOutcome.UPDATED
    assert repo.update_item(replace(item, status='processed', file_id=file.file_id)) == WriteOutcome.IDENTICAL
    assert repo.finish_run(run.run_id, 'complete', '2030-01-01T00:00:00+00:00') == WriteOutcome.UPDATED
    assert repo.create_run(run) == WriteOutcome.IDENTICAL
    assert repo.get_run(run.run_id).status == 'complete'


def test_transaction_rolls_back_on_conflict(store):
    repo, conn = store
    person, _, _ = records()
    with pytest.raises(ReproducibilityConflict):
        with repo.transaction():
            repo.register_person(person)
            repo.register_person(replace(person, local_alias='conflict'))
    assert conn.execute('SELECT count(*) FROM persons').fetchone()[0] == 0


def test_migration_v1_to_v2_and_checksum(tmp_path):
    path = tmp_path / 'db.sqlite'
    migrations = load_migrations()
    with open_database(path, mode='create', migrations=migrations[:1]):
        pass
    with open_database(path) as db:
        assert db.status.current_version == 1
        assert db.status.pending_versions == (2,)
    with open_database(path, mode='migrate') as db:
        assert db.status.current_version == 2
        assert verify_schema(db.connection).pending_versions == ()
        before = db.connection.execute('SELECT * FROM schema_migrations').fetchall()
    with open_database(path, mode='migrate') as db:
        assert db.connection.execute('SELECT * FROM schema_migrations').fetchall() == before
    changed = (migrations[0], Migration(2, migrations[1].sql + '\n-- changed'))
    with pytest.raises(MigrationChecksumError):
        with open_database(path, migrations=changed):
            pass


def test_new_database_only_expected_tables_and_integrity(store):
    _, conn = store
    expected = {'schema_migrations', 'persons', 'employers', 'corpora', 'source_files',
                'file_locations', 'ingest_runs', 'ingest_items'}
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")} == expected
    assert conn.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    assert verify_schema(conn).current_version == 2


@pytest.mark.parametrize('table', ['corpora', 'file_locations', 'ingest_items'])
def test_foreign_keys_all_restrict(store, table):
    _, conn = store
    fks = conn.execute(f'PRAGMA foreign_key_list({table})').fetchall()
    assert fks
    assert all(row[5:7] == ('RESTRICT', 'RESTRICT') for row in fks)


def populated(repo):
    person, corpus, file = records()
    repo.register_person(person)
    repo.register_corpus(corpus)
    repo.register_source_file(file)
    repo.register_location(FileLocation(corpus.corpus_id, 'a.pdf', file.file_id, 'a.pdf'))
    run = IngestRun.from_plan([])
    repo.create_run(run)
    repo.register_item(IngestItem(run.run_id, '1', corpus.corpus_id, 'a.pdf', file_id=file.file_id))
    return person, corpus, file, run


@pytest.mark.parametrize('table', ['persons', 'corpora', 'source_files', 'ingest_runs'])
@pytest.mark.parametrize('operation', ['DELETE', 'UPDATE'])
def test_referenced_identity_cannot_be_deleted_or_changed(store, table, operation):
    import sqlite3
    repo, conn = store
    person, corpus, file, run = populated(repo)
    key, value = {'persons': ('person_id', person.person_id), 'corpora': ('corpus_id', corpus.corpus_id),
                  'source_files': ('file_id', file.file_id), 'ingest_runs': ('run_id', run.run_id)}[table]
    sql = f'DELETE FROM {table}' if operation == 'DELETE' else f'UPDATE {table} SET {key}=?'
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, () if operation == 'DELETE' else (value[:-64] + 'f'*64,))


def test_missing_foreign_key_fails_and_does_not_write(store):
    import sqlite3
    repo, conn = store
    _, corpus, _ = records()
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_corpus(corpus)
    assert conn.execute('SELECT count(*) FROM corpora').fetchone() == (0,)


def test_tax_unique_index_is_enforced_by_sql(store):
    import sqlite3
    repo, conn = store
    first = Employer(employer_id('ES', 'A123'), 'ES', 'A123', 'First')
    repo.register_employer(first)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO employers VALUES (?, ?, ?, ?, ?)',
                     (employer_id('ES'), 'ES', 'A123', 'Second', first.created_at))
    repo.register_employer(Employer(employer_id('PT', 'A123'), 'PT', 'A123', 'Other country'))


@pytest.mark.parametrize('assignment', ['byte_size=-1', 'page_count=0', "availability='invalid'",
                                       "sha256='invalid'", "file_id='invalid'"])
def test_source_file_checks_enforced_by_sql(store, assignment):
    import sqlite3
    repo, conn = store
    _, _, file = records()
    repo.register_source_file(file)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'UPDATE source_files SET {assignment}')


def test_nested_transaction_rolls_back_only_failed_unit(store):
    repo, conn = store
    person, _, _ = records()
    other = Person(person_id(), 'other')
    with repo.transaction():
        repo.register_person(person)
        with pytest.raises(ReproducibilityConflict):
            with repo.transaction():
                repo.register_person(other)
                repo.register_person(replace(person, local_alias='conflict'))
        assert repo.get_person(other.person_id) is None
    assert conn.execute('SELECT count(*) FROM persons').fetchone() == (1,)


def test_file_expected_hash_mismatch_and_terminal_inventory(store):
    repo, _ = store
    _, corpus, file, run = populated(repo)
    bad = IngestItem(run.run_id, 'bad', corpus.corpus_id, 'b.pdf',
                     expected_sha256='f'*64, file_id=file.file_id)
    with pytest.raises(ReproducibilityConflict):
        repo.register_item(bad)
    with pytest.raises(ValueError):
        repo.finish_run(run.run_id, 'complete', '2030-01-01T00:00:00Z')
    item = repo.get_item(run.run_id, '1')
    failed = replace(item, status='failed', reason_code='read_failed',
                     error_detail='Traceback /private/secret.pdf')
    repo.update_item(failed)
    assert repo.get_item(run.run_id, '1').error_detail == 'Details omitted; see reason_code.'
    with pytest.raises(ReproducibilityConflict):
        repo.update_item(replace(item, status='processed'))
    repo.finish_run(run.run_id, 'partial', '2030-01-01T00:00:00Z')
    with pytest.raises(ReproducibilityConflict):
        repo.register_item(replace(item, item_key='new'))


def test_immutable_item_fields_cannot_change(store):
    repo, _ = store
    _, _, _, run = populated(repo)
    item = repo.get_item(run.run_id, '1')
    with pytest.raises(ReproducibilityConflict):
        repo.update_item(replace(item, relative_path='changed.pdf'))
    assert repo.get_item(run.run_id, '1') == item


def test_reopen_roundtrip_no_rows_leaked_and_verification(tmp_path):
    import sqlite3
    path = tmp_path / 'canonical.sqlite'
    with open_database(path, mode='create') as db:
        person, corpus, file, run = populated(EvidenceRepository(db.connection))
    with open_database(path) as db:
        repo = EvidenceRepository(db.connection)
        assert repo.get_person(person.person_id) == person
        assert not isinstance(repo.get_person(person.person_id), sqlite3.Row)
        assert repo.get_corpus(corpus.corpus_id) == corpus
        assert repo.get_source_file(file.file_id) == file
        assert repo.get_run(run.run_id) == run
        assert db.status.current_version == 2


def test_corpus_and_location_conflicts_preserve_evidence(store):
    repo, _ = store
    _, corpus, file, _ = populated(repo)
    with pytest.raises(ReproducibilityConflict):
        repo.register_corpus(replace(corpus, manifest_contract='different'))
    old = repo.get_location(corpus.corpus_id, 'a.pdf', file.file_id)
    with pytest.raises(ReproducibilityConflict):
        repo.register_location(replace(old, original_filename='different.pdf'))
    assert repo.get_location(corpus.corpus_id, 'a.pdf', file.file_id) == old
