"""Registered relational closure, without economic selection."""
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from src.candidacy_snapshot import CandidacySnapshotError, CandidacySnapshotLoader
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import Assessment, EconomicObservation, Rule, observation_id
from src.canonical.evidence import Corpus, Person, SourceFile, corpus_id, person_id, source_file_id
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.persistence import open_database
from src.persistence.relations import RelationRepository

STAMP = '2026-01-01T00:00:00Z'


def unit(repo, key, *, doc=None):
    person = Person(person_id(UUID(int=1)), 'synthetic', STAMP)
    corpus = Corpus(corpus_id(UUID(int=2)), person.person_id, 'synthetic', 'v1', STAMP)
    repo.register_person(person)
    repo.register_corpus(corpus)
    if doc is None:
        doc = LogicalDocument(document_id(corpus.corpus_id, key), corpus.corpus_id, None,
                              'synthetic', key, STAMP)
        repo.register_document(doc)
    file = SourceFile(source_file_id('a'*64), 'a'*64, 1, 'application/pdf', created_at=STAMP)
    repo.register_source_file(file)
    ver = DocumentVersion(version_id(doc.document_id, file.file_id, key), doc.document_id,
                          file.file_id, key, STAMP)
    repo.register_version(ver)
    ext = Extraction(extraction_id(ver.version_id, 'synthetic', '1', 'b'*64), ver.version_id,
                     'synthetic', '1', 'b'*64, 'c'*64, STAMP)
    repo.register_extraction(ext)
    fact = DocumentaryFact.from_draft(ext.extraction_id, FactDraft('synthetic',
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(10, 0))), created_at=STAMP)
    repo.register_fact(fact)
    rule = Rule.define('synthetic', 'snapshot', '1', 'a'*64, created_at=STAMP)
    repo.register_rule(rule)
    assessment = Assessment.from_facts(doc.document_id, rule.rule_id, (fact,), 'usable', created_at=STAMP)
    repo.register_assessment(assessment)
    obs = EconomicObservation(observation_id=observation_id(assessment.assessment_id, 'value'),
        assessment_id=assessment.assessment_id, observation_key='value', magnitude='synthetic',
        value=fact.value, economic_status='usable', eligibility='evidence_only', created_at=STAMP)
    repo.register_observation(obs, (fact.fact_id,))
    return doc, obs


@pytest.fixture
def store(tmp_path):
    path = tmp_path/'snapshot.sqlite'
    with open_database(path, mode='create') as db:
        repo = RelationRepository(db.connection)
        yield path, repo, db.connection


def edge(repo, source, target, kind='replaces'):
    repo.register_observation_relation(ObservationRelation.create(
        source.observation_id, target.observation_id, kind, reason_code='synthetic.link', created_at=STAMP))


def doc_edge(repo, source, target, kind='supersedes'):
    repo.register_document_relation(DocumentRelation.create(
        source.document_id, target.document_id, kind, reason_code='synthetic.link', created_at=STAMP))


def test_minimal_snapshot_and_read_only(store):
    path, repo, conn = store
    doc, obs = unit(repo, 'a')
    before = path.read_bytes()
    snapshot = CandidacySnapshotLoader(path).load_candidacy_snapshot(obs.observation_id)
    assert snapshot.target.observation == obs
    assert snapshot.documents == (doc,)
    assert len(snapshot.facts) == len(snapshot.extractions) == len(snapshot.versions) == 1
    assert snapshot.document_relations == snapshot.observation_relations == ()
    assert path.read_bytes() == before
    assert conn.execute('SELECT eligibility FROM economic_observations').fetchone() == ('evidence_only',)
    assert not hasattr(snapshot, 'complete')
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, 'scope', 'other')


@pytest.mark.parametrize('kind', ['contained_in', 'adjusts', 'replaces', 'complements'])
def test_observation_edges_both_directions_and_competitor(store, kind):
    path, repo, _ = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    _, c = unit(repo, 'c')
    unit(repo, 'unrelated')
    edge(repo, a, b, kind)
    edge(repo, c, b, kind)
    for target in (a, b, c):
        result = CandidacySnapshotLoader(path).load_candidacy_snapshot(target.observation_id)
        assert {e.observation.observation_id for e in result.observations} == {o.observation_id for o in (a, b, c)}
        assert len(result.observation_relations) == 2


@pytest.mark.parametrize('kind', ['duplicate_of', 'supersedes', 'complements',
                                  'same_logical_unit_pending_reconciliation'])
def test_document_relations_both_endpoints(store, kind):
    path, repo, _ = store
    a, obs = unit(repo, 'a')
    b, _ = unit(repo, 'b')
    c, _ = unit(repo, 'c')
    doc_edge(repo, a, b, kind)
    doc_edge(repo, c, b, kind)
    result = CandidacySnapshotLoader(path).load_candidacy_snapshot(obs.observation_id)
    assert {d.document_id for d in result.documents} == {a.document_id, b.document_id, c.document_id}
    assert len(result.document_relations) == 2


def test_cycles_siblings_and_versions_without_assessments(store):
    path, repo, _ = store
    doc, a = unit(repo, 'a')
    _, sibling = unit(repo, 'sibling', doc=doc)
    other, b = unit(repo, 'b')
    edge(repo, sibling, b)
    edge(repo, b, a)
    doc_edge(repo, doc, other)
    doc_edge(repo, other, doc)
    v = DocumentVersion(version_id(doc.document_id, source_file_id('a'*64), 'uninterpreted'),
                        doc.document_id, source_file_id('a'*64), 'uninterpreted', STAMP)
    repo.register_version(v)
    versions = repo.get_document_versions(doc.document_id)
    assert versions == tuple(sorted(versions, key=lambda item: item.version_id))
    assert len(versions) == 3 and v in versions
    result = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    assert len(result.assessments) == len(result.observations) == 3
    assert len(result.versions) == 4 and v in result.versions


def test_deterministic_across_insertion_order(tmp_path):
    snapshots = []
    for index, order in enumerate([('a', 'b', 'c'), ('c', 'b', 'a')]):
        path = tmp_path/f'{index}.sqlite'
        with open_database(path, mode='create') as db:
            repo = RelationRepository(db.connection)
            units = {key: unit(repo, key) for key in order}
            for key in order:
                if key != 'b':
                    edge(repo, units[key][1], units['b'][1])
            target = units['a'][1].observation_id
        snapshots.append(CandidacySnapshotLoader(path).load_candidacy_snapshot(target))
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize('corruption', ['support', 'fingerprint', 'reference'])
def test_broken_evidence_fails_closed(store, corruption):
    path, repo, conn = store
    _, obs = unit(repo, 'a')
    if corruption == 'support':
        conn.execute('DELETE FROM observation_facts')
    elif corruption == 'fingerprint':
        conn.execute('UPDATE documentary_facts SET coefficient=99')
    else:
        conn.execute('PRAGMA foreign_keys=OFF')
        conn.execute('DELETE FROM document_versions')
    with pytest.raises(CandidacySnapshotError):
        CandidacySnapshotLoader(path).load_candidacy_snapshot(obs.observation_id)


def test_missing_target(store):
    path, _, _ = store
    with pytest.raises(CandidacySnapshotError):
        CandidacySnapshotLoader(path).load_candidacy_snapshot('observation:sha256:'+'f'*64)


def test_loader_owns_one_verified_read_snapshot(store, monkeypatch):
    from contextlib import contextmanager

    import src.candidacy_snapshot as module
    path, repo, _ = store
    _, obs = unit(repo, 'a')
    original = module.open_database
    traces: list[str] = []
    @contextmanager
    def monitored(*args, **kwargs):
        assert kwargs['mode'] == 'verify'
        with original(*args, **kwargs) as db:
            assert db.connection.in_transaction
            assert db.connection.execute('PRAGMA query_only').fetchone() == (1,)
            db.connection.set_trace_callback(traces.append)
            yield db
            assert db.connection.total_changes == 0
    monkeypatch.setattr(module, 'open_database', monitored)
    CandidacySnapshotLoader(path).load_candidacy_snapshot(obs.observation_id)
    assert not any(sql.startswith(('COMMIT', 'RELEASE', 'INSERT', 'UPDATE', 'DELETE')) for sql in traces)
    assert any('FROM document_relations ORDER BY' in sql for sql in traces)
    assert any('FROM observation_relations ORDER BY' in sql for sql in traces)


def test_sibling_observations_inside_one_assessment_expand_context(store):
    from dataclasses import replace
    path, repo, _ = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    evidence = repo.get_observation(a.observation_id)
    sibling = replace(a, observation_key='other',
                      observation_id=observation_id(a.assessment_id, 'other'))
    repo.register_observation(sibling, evidence.fact_ids)
    edge(repo, sibling, b)
    snapshot = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    assert {e.observation.observation_id for e in snapshot.observations} == {
        a.observation_id, b.observation_id, sibling.observation_id}


def test_concurrent_relation_commit_does_not_mix_snapshots(store, monkeypatch):
    path, repo, conn = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    assert conn.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    original = RelationRepository.list_document_relations
    def commit_after_first_relation_read(reader):
        result = original(reader)
        edge(repo, a, b)
        return result
    monkeypatch.setattr(RelationRepository, 'list_document_relations', commit_after_first_relation_read)
    first = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    assert len(first.observations) == 1
    assert first.observation_relations == ()
    monkeypatch.setattr(RelationRepository, 'list_document_relations', original)
    second = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    assert len(second.observations) == 2 and len(second.observation_relations) == 1


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path/'absent.sqlite'
    with pytest.raises(CandidacySnapshotError):
        CandidacySnapshotLoader(path).load_candidacy_snapshot('observation:sha256:'+'f'*64)
    assert not path.exists()
