"""Logical-state fingerprints, material changes and independent reconstruction."""
from dataclasses import replace
from uuid import UUID

import pytest

from src.canonical.decisions import ManualDecision
from src.canonical.economics import Rule
from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.canonical_ingestion import CorpusInput, ingest
from src.manual_decisions import import_decisions
from src.persistence import load_migrations
from src.persistence import open_database as packaged_open_database
from src.persistence.decisions import DecisionRepository
from src.persistence.state import CanonicalStateReader, StateContractError
from tests.integration.ingestion.test_canonical_ingestion import SyntheticProcessor
from tests.integration.persistence.test_manual_decisions import STAMP, populate
from tests.integration.persistence.test_relations import unit


# Preserve the v7 fingerprint contract; v8 coverage lives in test_derived_results.
def open_database(path, **kwargs):
    kwargs.setdefault('migrations', load_migrations()[:7])
    return packaged_open_database(path, **kwargs)


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = DecisionRepository(db.connection)
        fact = populate(repo)
        yield repo, db.connection, fact


def snapshot(store, strict=False):
    return CanonicalStateReader(store[1]).read(include_operational_metadata=strict)


def test_snapshot_is_versioned_deterministic_and_covers_every_table(store):
    first = snapshot(store)
    assert first == snapshot(store)
    assert len(first.fingerprint) == 64
    assert len(first.table_counts) == 21
    assert dict(first.table_counts)['documentary_facts'] == 1
    assert b'canonical-persisted-state/v1' in first.canonical_content
    assert b'manual_decisions' in first.canonical_content


@pytest.mark.parametrize('table,column', [
    ('schema_migrations', 'applied_at'), ('persons', 'created_at'),
    ('source_files', 'created_at'), ('documentary_facts', 'created_at'),
])
def test_operational_timestamps_excluded_only_from_logical_mode(store, table, column):
    logical, strict = snapshot(store), snapshot(store, True)
    store[1].execute(f'UPDATE {table} SET {column}=?', ('2030-01-01T00:00:00Z',))
    assert snapshot(store) == logical
    assert snapshot(store, True).fingerprint != strict.fingerprint


@pytest.mark.parametrize('sql', [
    'UPDATE documentary_facts SET coefficient=999',
    "UPDATE source_files SET availability='withdrawn'",
    "UPDATE schema_migrations SET application_revision='other-revision'",
    'DELETE FROM fact_pages',
])
def test_material_evidence_or_revision_changes_fingerprint(store, sql):
    before = snapshot(store)
    store[1].execute(sql)
    assert snapshot(store).fingerprint != before.fingerprint


@pytest.mark.parametrize('version,digest', [('2', 'a'*64), ('1', 'b'*64)])
def test_rule_version_or_implementation_changes_fingerprint(store, version, digest):
    repo, _, _ = store
    repo.register_rule(Rule.define('synthetic', 'rule', '1', 'a'*64, created_at=STAMP))
    before = snapshot(store)
    repo.register_rule(Rule.define('synthetic', 'rule', version, digest, created_at=STAMP))
    assert snapshot(store).fingerprint != before.fingerprint


def test_valid_human_decision_changes_state_and_replay_does_not(store):
    repo, _, fact = store
    before = snapshot(store)
    decision = ManualDecision.create(fact.fact_id, repo.precondition_hash('documentary_fact', fact.fact_id),
                                     created_by='synthetic-reviewer', created_at=STAMP)
    repo.register_decision(decision)
    after = snapshot(store)
    assert after.fingerprint != before.fingerprint
    strict = snapshot(store, True)
    import_decisions(repo, repo.export_decisions())
    assert snapshot(store) == after and snapshot(store, True) == strict


@pytest.mark.parametrize('kind', ['document', 'observation'])
def test_relations_change_fingerprint(kind):
    with open_database(':memory:', mode='create') as db:
        repo = DecisionRepository(db.connection)
        person = Person(person_id(UUID(int=1)), 'synthetic')
        corpus = Corpus(corpus_id(UUID(int=2)), person.person_id, 'synthetic', 'v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        a, _, oa = unit((repo, db.connection, corpus), 'a')
        b, _, ob = unit((repo, db.connection, corpus), 'b')
        reader = CanonicalStateReader(db.connection)
        before = reader.read()
        if kind == 'document':
            repo.register_document_relation(DocumentRelation.create(a.document_id, b.document_id, 'complements', reason_code='synthetic'))
        else:
            repo.register_observation_relation(ObservationRelation.create(oa.observation_id, ob.observation_id, 'complements', reason_code='synthetic'))
        assert reader.read().fingerprint != before.fingerprint


def test_physical_row_order_is_irrelevant():
    results = []
    for order in ((1, 2, 3), (3, 1, 2)):
        with open_database(':memory:', mode='create') as db:
            repo = DecisionRepository(db.connection)
            for number in order:
                repo.register_person(Person(person_id(UUID(int=number)), str(number), STAMP))
            results.append(CanonicalStateReader(db.connection).read())
    assert results[0] == results[1]


def test_two_new_builds_portable_decisions_relations_and_same_db_replay(tmp_path):
    logical, strict = [], []
    portable = None
    for label, order in [('a', (1, 2)), ('b', (2, 1))]:
        root = tmp_path/label
        root.mkdir()
        for number in order:
            (root/f'{number}.pdf').write_bytes(f'synthetic{number}'.encode())
        with open_database(tmp_path/f'{label}.sqlite', mode='create') as db:
            repo = DecisionRepository(db.connection)
            person = Person(person_id(UUID(int=1)), 'synthetic')
            corpus = Corpus(corpus_id(UUID(int=2)), person.person_id, 'synthetic', 'v1')
            repo.register_person(person)
            repo.register_corpus(corpus)
            bindings = [CorpusInput(corpus.corpus_id, root, 'synthetic')]
            processor = SyntheticProcessor()
            result = ingest(repo, bindings, {'synthetic': processor})
            assert result.processed == 2 and result.failed == 0
            assessments = repo.list_assessments()
            observations = [repo.get_observations(a.assessment_id)[0].observation for a in assessments]
            repo.register_document_relation(DocumentRelation.create(assessments[0].document_id, assessments[1].document_id,
                                             'complements', reason_code='synthetic', created_at=STAMP))
            repo.register_observation_relation(ObservationRelation.create(observations[0].observation_id, observations[1].observation_id,
                                                'complements', reason_code='synthetic', created_at=STAMP))
            if portable is None:
                fact = repo.get_fact(assessments[0].inputs[0].fact_id)
                assert fact is not None
                decision = ManualDecision.create(fact.fact_id, repo.precondition_hash('documentary_fact', fact.fact_id),
                                                 created_by='synthetic-reviewer', created_at=STAMP)
                repo.register_decision(decision)
                portable = repo.export_decisions()
            else:
                import_decisions(repo, portable)
            reader = CanonicalStateReader(db.connection)
            logical.append(reader.read())
            strict.append(reader.read(include_operational_metadata=True))
            assert ingest(repo, bindings, {'synthetic': processor}) == result
            assert len(processor.calls) == 2
            assert reader.read() == logical[-1]
            assert reader.read(include_operational_metadata=True) == strict[-1]
    assert logical[0] == logical[1]
    assert strict[0].fingerprint != strict[1].fingerprint


def test_relative_path_is_semantic_not_silently_normalized(store):
    from src.canonical.evidence import FileLocation, source_file_id
    repo, _, _ = store
    a = FileLocation(corpus_id(UUID(int=2)), 'one.pdf', source_file_id('a'*64), 'one.pdf', STAMP)
    repo.register_location(a)
    before = snapshot(store)
    repo.register_location(replace(a, relative_path='two.pdf', original_filename='two.pdf'))
    assert snapshot(store).fingerprint != before.fingerprint


@pytest.mark.parametrize('sql', ['CREATE TABLE forgotten(value TEXT)', 'DROP TABLE manual_decisions'])
def test_schema_drift_not_silently_omitted(store, sql):
    store[1].execute(sql)
    with pytest.raises(StateContractError):
        snapshot(store)


def test_older_schema_rejected():
    with open_database(':memory:', mode='create', migrations=load_migrations()[:6]) as db:
        with pytest.raises(StateContractError):
            CanonicalStateReader(db.connection).read()


def test_human_decision_audit_timestamp_is_preserved():
    results = []
    for stamp in (STAMP, '2030-01-01T00:00:00Z'):
        with open_database(':memory:', mode='create') as db:
            repo = DecisionRepository(db.connection)
            fact = populate(repo)
            repo.register_decision(ManualDecision.create(fact.fact_id,
                repo.precondition_hash('documentary_fact', fact.fact_id), created_by='synthetic', created_at=stamp))
            results.append(CanonicalStateReader(db.connection).read())
    assert results[0].fingerprint != results[1].fingerprint


def test_snapshot_is_read_only_and_changes_nothing(tmp_path):
    path = tmp_path/'state.sqlite'
    with open_database(path, mode='create') as db:
        populate(DecisionRepository(db.connection))
        before = CanonicalStateReader(db.connection).read(include_operational_metadata=True)
    with open_database(path) as db:
        reader = CanonicalStateReader(db.connection)
        assert reader.read(include_operational_metadata=True) == before
        assert db.connection.execute('PRAGMA query_only').fetchone()[0] == 1


def test_extra_column_is_included_instead_of_silently_lost(store):
    before = snapshot(store)
    store[1].execute('ALTER TABLE persons ADD COLUMN synthetic_extension TEXT')
    after = snapshot(store)
    assert after.fingerprint != before.fingerprint
    assert b'synthetic_extension' in after.canonical_content


def test_noncanonical_real_value_rejected(store):
    store[1].execute('ALTER TABLE persons ADD COLUMN synthetic_extension REAL')
    store[1].execute('UPDATE persons SET synthetic_extension=0.5')
    with pytest.raises(StateContractError):
        snapshot(store)
