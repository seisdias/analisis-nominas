"""Synthetic portable human decisions and exclusive-file reconstruction."""
import json
import sqlite3
from dataclasses import replace
from uuid import UUID

import pytest

from src.canonical import CanonicalValue, ExactDecimal, ReproducibilityConflict, ValueState
from src.canonical.decisions import ManualDecision, decode_decisions, encode_decisions
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    VersionPage,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.evidence import Corpus, Person, SourceFile, corpus_id, person_id, source_file_id
from src.canonical.facts import DocumentaryFact, FactDraft, FactPage
from src.manual_decisions import (
    DecisionPreconditionConflict,
    import_decisions,
    rebuild_with_decisions,
)
from src.persistence import load_migrations, open_database, verify_schema
from src.persistence.decisions import DecisionRepository
from src.persistence.evidence import WriteOutcome

STAMP = '2026-01-01T00:00:00Z'


def populate(repo, amount=100, stamp=STAMP):
    person = Person(person_id(UUID(int=1)), 'synthetic', stamp)
    corpus = Corpus(corpus_id(UUID(int=2)), person.person_id, 'synthetic', 'v1', stamp)
    repo.register_person(person)
    repo.register_corpus(corpus)
    file = SourceFile(source_file_id('a'*64), 'a'*64, 42, 'application/pdf', 2, created_at=stamp)
    repo.register_source_file(file)
    doc = LogicalDocument(document_id(corpus.corpus_id, 'first'), corpus.corpus_id, None, 'synthetic', 'first', stamp)
    repo.register_document(doc)
    version = DocumentVersion(version_id(doc.document_id, file.file_id, 'page1'), doc.document_id, file.file_id, 'page1', stamp)
    repo.register_version(version)
    repo.associate_page(VersionPage(version.version_id, 1, 0))
    extraction = Extraction(extraction_id(version.version_id, 'synthetic', '1', 'b'*64), version.version_id, 'synthetic', '1', 'b'*64, 'c'*64, stamp)
    repo.register_extraction(extraction)
    fact = DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('synthetic.amount', CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(amount, 0))), created_at=stamp)
    repo.register_fact(fact)
    repo.associate_fact_page(FactPage(fact.fact_id, 1))
    return fact


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = DecisionRepository(db.connection)
        fact = populate(repo)
        yield repo, db.connection, fact


def decision(repo, fact, actor='local-reviewer'):
    return ManualDecision.create(fact.fact_id, repo.precondition_hash('documentary_fact', fact.fact_id),
                                 created_by=actor, created_at=STAMP)


def test_persistence_export_import_roundtrip_idempotence(store):
    repo, conn, fact = store
    item = decision(repo, fact)
    assert repo.register_decision(item) == WriteOutcome.CREATED
    assert repo.register_decision(replace(item, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_decision(item.decision_id) == item
    data = repo.export_decisions()
    assert decode_decisions(data) == (item,)
    before = tuple(conn.iterdump())
    assert import_decisions(repo, data).decision_ids == (item.decision_id,)
    assert tuple(conn.iterdump()) == before
    assert repo.export_decisions() == data


def test_export_order_independent_and_duplicate_decision(store):
    repo, _, fact = store
    a, b = decision(repo, fact), decision(repo, fact, 'other')
    assert encode_decisions((a, b)) == encode_decisions((b, a))
    assert decode_decisions(encode_decisions((a, a))) == (a,)
    import_decisions(repo, encode_decisions((a, a)))
    assert len(repo.list_decisions()) == 1


@pytest.mark.parametrize('field,value', [('payload_json', '{"acknowledged":false}'), ('precondition_hash', 'd'*64), ('created_by', 'other')])
def test_same_identity_altered_content_conflicts(store, field, value):
    repo, _, fact = store
    with pytest.raises(ReproducibilityConflict):
        replace(decision(repo, fact), **{field: value})


@pytest.mark.parametrize('mutation', ['value', 'source', 'page', 'missing'])
def test_changed_evidence_and_missing_target_block_without_writes(store, mutation):
    repo, conn, fact = store
    bundle = encode_decisions((decision(repo, fact),))
    if mutation == 'value':
        conn.execute('UPDATE documentary_facts SET coefficient=999 WHERE fact_id=?', (fact.fact_id,))
    elif mutation == 'source':
        conn.execute("UPDATE source_files SET availability='withdrawn'")
    elif mutation == 'page':
        conn.execute('DELETE FROM fact_pages')
    else:
        conn.execute('DELETE FROM fact_pages')
        conn.execute('DELETE FROM documentary_facts')
    with pytest.raises(DecisionPreconditionConflict) as error:
        import_decisions(repo, bundle)
    assert error.value.publication_blocked
    assert not repo.list_decisions()


def test_batch_failure_rolls_back(store):
    repo, conn, fact = store
    good = decision(repo, fact)
    absent = ManualDecision.create('fact:sha256:'+'f'*64, 'a'*64, created_by='test', created_at=STAMP)
    before = tuple(conn.iterdump())
    with pytest.raises(DecisionPreconditionConflict):
        import_decisions(repo, encode_decisions((good, absent)))
    assert tuple(conn.iterdump()) == before


@pytest.mark.parametrize('mutation', ['version', 'float', 'payload', 'duplicate_key'])
def test_portable_format_rejects_alterations(store, mutation):
    repo, _, fact = store
    data = encode_decisions((decision(repo, fact),))
    obj = json.loads(data)
    if mutation == 'version':
        obj['version'] = 2
    if mutation == 'float':
        obj['decisions'][0]['payload_json'] = '{"acknowledged":1.1}'
    if mutation == 'payload':
        obj['decisions'][0]['precondition_hash'] = 'b'*64
    if mutation == 'duplicate_key':
        data = data.replace(b'"version":1', b'"version":1,"version":1')
    else:
        data = json.dumps(obj).encode()
    with pytest.raises((ValueError, TypeError)):
        import_decisions(repo, data)
    assert not repo.list_decisions()


def test_rebuild_new_file_equivalent_and_source_untouched(tmp_path):
    source, target = tmp_path/'source.sqlite', tmp_path/'new.sqlite'
    with open_database(source, mode='create') as db:
        repo = DecisionRepository(db.connection)
        fact = populate(repo)
        repo.register_decision(decision(repo, fact))
        portable = repo.export_decisions()
        expected = {table: db.connection.execute(f'SELECT * FROM {table}').fetchall() for table in
                    ('persons', 'corpora', 'source_files', 'logical_documents', 'document_versions',
                     'version_pages', 'extractions', 'documentary_facts', 'fact_pages', 'manual_decisions')}
    original = source.read_bytes()
    result = rebuild_with_decisions(target, portable, populate)
    assert result.decisions_validated and result.path == target
    with open_database(target) as db:
        assert verify_schema(db.connection).current_version == len(load_migrations())
        for table, rows in expected.items():
            assert db.connection.execute(f'SELECT * FROM {table}').fetchall() == rows
        assert DecisionRepository(db.connection).export_decisions() == portable
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        rebuild_with_decisions(source, portable, populate)
    assert source.read_bytes() == original


def test_rebuild_stale_blocked_and_population_rolled_back(store, tmp_path):
    repo, _, fact = store
    path = tmp_path/'blocked.sqlite'
    with pytest.raises(DecisionPreconditionConflict):
        rebuild_with_decisions(path, encode_decisions((decision(repo, fact),)), lambda r: populate(r, 101))
    with open_database(path) as db:
        assert db.connection.execute('SELECT count(*) FROM documentary_facts').fetchone()[0] == 0
        assert db.connection.execute('SELECT count(*) FROM manual_decisions').fetchone()[0] == 0


def test_operational_timestamp_not_precondition(store):
    repo, _, fact = store
    item = decision(repo, fact)
    with open_database(':memory:', mode='create') as db:
        other = DecisionRepository(db.connection)
        populate(other, stamp='2030-01-01T00:00:00Z')
        assert import_decisions(other, encode_decisions((item,))).decision_ids == (item.decision_id,)


@pytest.mark.parametrize('upgrade', [False, True])
def test_schema_v7_upgrade_reopen_integrity(tmp_path, upgrade):
    path = tmp_path/'schema.sqlite'
    if upgrade:
        with open_database(path, mode='create', migrations=load_migrations()[:6]):
            pass
    with open_database(path, mode='migrate' if upgrade else 'create', migrations=load_migrations()[:7]) as db:
        assert verify_schema(db.connection, load_migrations()[:7]).current_version == 7
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        before = tuple(db.connection.iterdump())
    with open_database(path, mode='migrate', migrations=load_migrations()[:7]) as db:
        assert tuple(db.connection.iterdump()) == before


@pytest.mark.parametrize('sql', ['DELETE FROM manual_decisions', "UPDATE manual_decisions SET created_by='other'"])
def test_append_only_sql_guard(store, sql):
    repo, conn, fact = store
    repo.register_decision(decision(repo, fact))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql)


def test_transaction_rolls_back_successful_registration_on_later_conflict(store):
    repo, conn, fact = store
    item = decision(repo, fact)
    before = tuple(conn.iterdump())
    with pytest.raises(DecisionPreconditionConflict):
        with repo.transaction():
            repo.register_decision(item)
            assert len(repo.list_decisions()) == 1
            repo.register_decision(ManualDecision.create(fact.fact_id, 'd'*64, created_by='test', created_at=STAMP))
    assert tuple(conn.iterdump()) == before


def test_extraction_peer_change_invalidates_acknowledgement(store):
    repo, _, fact = store
    item = decision(repo, fact)
    peer = DocumentaryFact.from_draft(fact.extraction_id, FactDraft('another', CanonicalValue(state=ValueState.UNKNOWN)), created_at=STAMP)
    repo.register_fact(peer)
    with pytest.raises(DecisionPreconditionConflict):
        import_decisions(repo, encode_decisions((item,)))


def test_export_retains_obsolete_history_but_empty_import_cannot_bypass_it(store):
    repo, conn, fact = store
    repo.register_decision(decision(repo, fact))
    before = repo.export_decisions()
    conn.execute("UPDATE source_files SET availability='withdrawn'")
    assert repo.export_decisions() == before
    with pytest.raises(DecisionPreconditionConflict):
        import_decisions(repo, encode_decisions(()))
    assert len(repo.list_decisions()) == 1


def test_conflicting_duplicate_portable_audit_record_rejected(store):
    repo, _, fact = store
    item = decision(repo, fact)
    with pytest.raises(ReproducibilityConflict):
        encode_decisions((item, replace(item, created_at='2030-01-01T00:00:00Z')))


def test_acknowledgement_has_no_economic_effect(store):
    repo, conn, fact = store
    import_decisions(repo, encode_decisions((decision(repo, fact),)))
    for table in ('assessments', 'economic_observations', 'document_relations', 'observation_relations'):
        assert conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
    assert repo.get_fact(fact.fact_id) == fact


@pytest.mark.parametrize('actor', ['', '/private/user', '../user', 'name@example.com'])
def test_actor_alias_rejects_empty_paths_and_email(store, actor):
    repo, _, fact = store
    with pytest.raises(ValueError):
        decision(repo, fact, actor)


def test_rebuild_rejects_symlink_to_source(store, tmp_path):
    repo, _, fact = store
    source = tmp_path/'source.sqlite'
    source.write_bytes(b'untouched')
    alias = tmp_path/'alias.sqlite'
    alias.symlink_to(source)
    with pytest.raises(FileExistsError):
        rebuild_with_decisions(alias, encode_decisions((decision(repo, fact),)), populate)
    assert source.read_bytes() == b'untouched'


def test_malformed_portable_creates_no_file(tmp_path):
    path = tmp_path/'never.sqlite'
    with pytest.raises(ValueError):
        rebuild_with_decisions(path, b'{"version":999}', populate)
    assert not path.exists()


def test_v7_checksum_is_protected(store):
    from src.persistence import MigrationChecksumError

    _, conn, _ = store
    conn.execute("UPDATE schema_migrations SET checksum=? WHERE version=7", ('f'*64,))
    with pytest.raises(MigrationChecksumError):
        verify_schema(conn)
