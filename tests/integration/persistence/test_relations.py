"""Synthetic explicit relations and conservative candidate selection."""

import sqlite3
from dataclasses import replace

import pytest

from src.candidate_selection import select_candidates
from src.canonical import (
    CanonicalValue,
    ExactDecimal,
    ReproducibilityConflict,
    ValueState,
)
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import (
    Assessment,
    EconomicObservation,
    Rule,
    observation_id,
)
from src.canonical.evidence import (
    Corpus,
    Person,
    SourceFile,
    corpus_id,
    person_id,
    source_file_id,
)
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.persistence import load_migrations, open_database, verify_schema
from src.persistence.evidence import WriteOutcome
from src.persistence.relations import RelationRepository

STAMP = '2026-01-01T00:00:00Z'
DOC_TYPES = ('duplicate_of', 'supersedes', 'complements', 'same_logical_unit_pending_reconciliation')
OBS_TYPES = ('contained_in', 'adjusts', 'replaces', 'complements')


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        yield repo, db.connection, corpus


def unit(store, key, *, doc=None, segment='whole', assessment_status='usable',
         economic_status='usable', eligibility='candidate', value=None, stamp=STAMP):
    repo, _, corpus = store
    if doc is None:
        doc = LogicalDocument(document_id(corpus.corpus_id, key), corpus.corpus_id, None, 'unknown', key)
        repo.register_document(doc)
    file = SourceFile(source_file_id('a'*64), 'a'*64, 1, 'application/pdf')
    repo.register_source_file(file)
    version = DocumentVersion(version_id(doc.document_id, file.file_id, segment), doc.document_id, file.file_id, segment)
    repo.register_version(version)
    extraction = Extraction(extraction_id(version.version_id, 'synthetic', key, 'b'*64), version.version_id, 'synthetic', key, 'b'*64, 'c'*64)
    repo.register_extraction(extraction)
    fact = DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('synthetic.amount',
           value if value is not None else CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(10, 0))))
    repo.register_fact(fact)
    rule = Rule.define('synthetic', 'candidate', '1', 'a'*64)
    repo.register_rule(rule)
    assessment = Assessment.from_facts(doc.document_id, rule.rule_id, (fact,), assessment_status, created_at=stamp)
    repo.register_assessment(assessment)
    obs = EconomicObservation(observation_id=observation_id(assessment.assessment_id, 'amount'),
        assessment_id=assessment.assessment_id, observation_key='amount', magnitude='synthetic',
        value=fact.value, economic_status=economic_status, eligibility=eligibility, created_at=stamp)
    repo.register_observation(obs, (fact.fact_id,))
    return doc, assessment, obs


@pytest.mark.parametrize('kind', DOC_TYPES)
def test_document_relation_types_idempotence_and_direction(store, kind):
    repo, _, _ = store
    a, _, _ = unit(store, 'a')
    b, _, _ = unit(store, 'b')
    rel = DocumentRelation.create(a.document_id, b.document_id, kind, reason_code='synthetic.reason', created_at=STAMP)
    reverse = DocumentRelation.create(b.document_id, a.document_id, kind, reason_code='synthetic.reason', created_at=STAMP)
    assert (rel == reverse) == (kind != 'supersedes')
    assert repo.register_document_relation(rel) == WriteOutcome.CREATED
    assert repo.register_document_relation(replace(rel, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_document_relation(rel.relation_id) == rel
    with pytest.raises(ReproducibilityConflict):
        repo.register_document_relation(replace(rel, reason_code='different.reason'))


@pytest.mark.parametrize('kind', OBS_TYPES)
def test_observation_relation_types_idempotence_and_direction(store, kind):
    repo, _, _ = store
    _, assessment, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    rel = ObservationRelation.create(a.observation_id, b.observation_id, kind,
                                     rule_id=assessment.rule_id, created_at=STAMP)
    reverse = ObservationRelation.create(b.observation_id, a.observation_id, kind,
                                         rule_id=assessment.rule_id, created_at=STAMP)
    assert (rel == reverse) == (kind == 'complements')
    assert repo.register_observation_relation(rel) == WriteOutcome.CREATED
    assert repo.register_observation_relation(rel) == WriteOutcome.IDENTICAL
    assert repo.get_observation_relation(rel.relation_id) == rel
    with pytest.raises(ReproducibilityConflict):
        repo.register_observation_relation(replace(rel, reason_code='changed.reason'))


@pytest.mark.parametrize('kind', DOC_TYPES)
def test_document_self_relation_rejected(kind):
    with pytest.raises(ValueError):
        DocumentRelation.create('document:sha256:'+'a'*64, 'document:sha256:'+'a'*64, kind, reason_code='test')


@pytest.mark.parametrize('kind', OBS_TYPES)
def test_observation_self_relation_rejected(kind):
    with pytest.raises(ValueError):
        ObservationRelation.create('observation:sha256:'+'a'*64, 'observation:sha256:'+'a'*64, kind, reason_code='test')


def test_relation_requires_explicit_provenance(store):
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    with pytest.raises(ValueError):
        ObservationRelation.create(a.observation_id, b.observation_id, 'replaces')


def test_replaces_excludes_target_and_does_not_change_facts(store):
    repo, conn, _ = store
    _, _, old = unit(store, 'old')
    _, _, new = unit(store, 'new', stamp='2020-01-01T00:00:00Z')  # Earlier timestamp is irrelevant.
    before = conn.execute('SELECT * FROM documentary_facts ORDER BY fact_id').fetchall()
    repo.register_observation_relation(ObservationRelation.create(new.observation_id, old.observation_id, 'replaces', reason_code='explicit.replacement'))
    result = select_candidates(repo)
    assert [item.observation for item in result.candidates] == [new]
    assert result.decision(old.observation_id).status == 'excluded'
    assert conn.execute('SELECT * FROM documentary_facts ORDER BY fact_id').fetchall() == before


def test_inadmissible_replacement_does_not_promote_or_reactivate_target(store):
    repo, _, _ = store
    _, _, old = unit(store, 'old')
    _, _, new = unit(store, 'new', eligibility='evidence_only')
    repo.register_observation_relation(ObservationRelation.create(new.observation_id, old.observation_id, 'replaces', reason_code='explicit.replacement'))
    assert select_candidates(repo).candidates == ()


@pytest.mark.parametrize('status', ['pending', 'ambiguous', 'excluded', 'incomplete'])
def test_assessment_states_not_promoted(store, status):
    repo, _, _ = store
    _, _, obs = unit(store, status, assessment_status=status, economic_status=status,
                     eligibility='excluded' if status == 'excluded' else 'evidence_only')
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(obs.observation_id).status != 'candidate'


@pytest.mark.parametrize('kind', ['contained_in', 'adjusts', 'complements'])
def test_relations_do_not_sum_or_choose_a_side(store, kind):
    repo, _, _ = store
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    repo.register_observation_relation(ObservationRelation.create(a.observation_id, b.observation_id, kind, reason_code='explicit.relationship'))
    result = select_candidates(repo)
    assert {x.observation.observation_id for x in result.candidates} == {a.observation_id, b.observation_id}
    assert all(x.observation.value.value == ExactDecimal(10, 0) for x in result.candidates)


def test_no_latest_version_or_assessment_selection(store):
    repo, _, _ = store
    doc, _, a = unit(store, 'a', segment='v1')
    _, _, b = unit(store, 'b', doc=doc, segment='v2', stamp='2030-01-01T00:00:00Z')
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(a.observation_id).status == 'ambiguous'
    assert result.decision(b.observation_id).status == 'ambiguous'
    repo.register_observation_relation(ObservationRelation.create(a.observation_id, b.observation_id, 'replaces', reason_code='explicit.replacement'))
    assert [x.observation for x in select_candidates(repo).candidates] == [a]


@pytest.mark.parametrize('kind', ['duplicate_of', 'same_logical_unit_pending_reconciliation'])
def test_symmetric_document_uncertainty_has_no_winner(store, kind):
    repo, _, _ = store
    a, _, _ = unit(store, 'a')
    b, _, _ = unit(store, 'b')
    repo.register_document_relation(DocumentRelation.create(a.document_id, b.document_id, kind, reason_code='explicit.relationship'))
    result = select_candidates(repo)
    assert not result.candidates
    assert all(d.status in ('pending', 'ambiguous') for d in result.decisions)


def test_document_supersedes_and_complements(store):
    repo, _, _ = store
    old_doc, _, old = unit(store, 'old')
    new_doc, _, new = unit(store, 'new')
    repo.register_document_relation(DocumentRelation.create(new_doc.document_id, old_doc.document_id, 'complements', reason_code='explicit.relationship'))
    assert len(select_candidates(repo).candidates) == 2
    repo.register_document_relation(DocumentRelation.create(new_doc.document_id, old_doc.document_id, 'supersedes', reason_code='explicit.replacement'))
    result = select_candidates(repo)
    assert [x.observation for x in result.candidates] == [new]
    assert result.decision(old.observation_id).status == 'excluded'


def test_competing_replacements_remain_ambiguous(store):
    repo, _, _ = store
    _, _, old = unit(store, 'old')
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    for replacement in (a, b):
        repo.register_observation_relation(ObservationRelation.create(replacement.observation_id, old.observation_id, 'replaces', reason_code='explicit.replacement'))
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(a.observation_id).status == 'ambiguous'
    assert result.decision(b.observation_id).status == 'ambiguous'


def test_relation_conflict_rolls_back(store):
    repo, conn, _ = store
    a, _, _ = unit(store, 'a')
    b, _, _ = unit(store, 'b')
    rel = DocumentRelation.create(a.document_id, b.document_id, 'complements', reason_code='test')
    with pytest.raises(ReproducibilityConflict):
        with repo.transaction():
            repo.register_document_relation(rel)
            repo.register_document_relation(replace(rel, reason_code='changed'))
    assert conn.execute('SELECT count(*) FROM document_relations').fetchone() == (0,)


@pytest.mark.parametrize('table', ['document_relations', 'observation_relations'])
def test_foreign_key_policy_and_missing_endpoints(store, table):
    repo, conn, _ = store
    doc, _, obs = unit(store, 'a')
    rows = conn.execute(f'PRAGMA foreign_key_list({table})').fetchall()
    assert len(rows) == 3 and all(r[5:7] == ('RESTRICT', 'RESTRICT') for r in rows)
    with pytest.raises(sqlite3.IntegrityError):
        if table == 'document_relations':
            repo.register_document_relation(DocumentRelation.create(doc.document_id, 'document:sha256:'+'f'*64, 'supersedes', reason_code='test'))
        else:
            repo.register_observation_relation(ObservationRelation.create(obs.observation_id, 'observation:sha256:'+'f'*64, 'replaces', reason_code='test'))


@pytest.mark.parametrize('upgrade', [False, True])
def test_v6_upgrade_integrity_reopen(tmp_path, upgrade):
    path = tmp_path / 'synthetic.sqlite'
    if upgrade:
        with open_database(path, mode='create', migrations=load_migrations()[:5]):
            pass
        with open_database(path) as db:
            assert db.status.pending_versions == (6,)
    with open_database(path, mode='migrate' if upgrade else 'create') as db:
        assert verify_schema(db.connection).current_version == 6
        tables = {r[0] for r in db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert tables == {'schema_migrations', 'persons', 'employers', 'corpora', 'source_files',
                          'file_locations', 'ingest_runs', 'ingest_items', 'logical_documents',
                          'document_versions', 'version_pages', 'extractions', 'documentary_facts',
                          'fact_pages', 'rules', 'assessments', 'economic_observations', 'observation_facts',
                          'document_relations', 'observation_relations'}
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        before = db.connection.execute('SELECT * FROM schema_migrations').fetchall()
    with open_database(path, mode='migrate') as db:
        assert db.connection.execute('SELECT * FROM schema_migrations').fetchall() == before


def test_overlapping_replacement_disputes_are_not_resolved_by_iteration_order(store):
    repo, _, _ = store
    _, _, old1 = unit(store, 'old1')
    _, _, old2 = unit(store, 'old2')
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    _, _, c = unit(store, 'c')
    for source, target in [(a, old1), (b, old1), (b, old2), (c, old2)]:
        repo.register_observation_relation(ObservationRelation.create(source.observation_id, target.observation_id,
                                            'replaces', reason_code='explicit.replacement'))
    result = select_candidates(repo)
    assert not result.candidates
    assert all(result.decision(obs.observation_id).status == 'ambiguous' for obs in (a, b, c))


@pytest.mark.parametrize('state', [ValueState.UNKNOWN, ValueState.UNRELIABLE])
def test_uncertain_value_not_promoted(store, state):
    repo, _, _ = store
    value = CanonicalValue(state=state, value=ExactDecimal(0, 0) if state == ValueState.UNRELIABLE else None,
                           reason_code='legacy.zero_origin_unknown' if state == ValueState.UNRELIABLE else None)
    _, _, obs = unit(store, 'uncertain', economic_status='pending', eligibility='evidence_only', value=value)
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(obs.observation_id).evidence.observation.value == value
    assert result.decision(obs.observation_id).status == 'pending'


def test_evidence_only_not_promoted_and_present_zero_can_be_candidate(store):
    repo, _, _ = store
    _, _, evidence = unit(store, 'evidence', eligibility='evidence_only')
    _, _, zero = unit(store, 'zero', value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0)))
    result = select_candidates(repo)
    assert [x.observation for x in result.candidates] == [zero]
    assert result.decision(evidence.observation_id).reason_code == 'eligibility.evidence_only'


def test_candidate_rechecks_fact_fingerprint(store):
    repo, conn, _ = store
    _, _, obs = unit(store, 'a')
    # Synthetic corruption, never a production update API.
    conn.execute('UPDATE documentary_facts SET coefficient=11')
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(obs.observation_id).reason_code == 'provenance.not_verified'


def test_missing_support_fails_closed(store):
    repo, conn, _ = store
    unit(store, 'a')
    conn.execute('DELETE FROM observation_facts')
    with pytest.raises(ValueError):
        select_candidates(repo)


def test_cycles_do_not_pick_a_winner(store):
    repo, _, _ = store
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    for source, target in [(a, b), (b, a)]:
        repo.register_observation_relation(ObservationRelation.create(source.observation_id, target.observation_id,
                                            'replaces', reason_code='explicit.replacement'))
    assert not select_candidates(repo).candidates


def test_relation_provenance_rule_fk_restrict(store):
    repo, conn, _ = store
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    unknown = 'rule:sha256:' + 'f'*64
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_observation_relation(ObservationRelation.create(a.observation_id, b.observation_id,
                                            'replaces', rule_id=unknown))
    rule = Rule.define('synthetic', 'relation_only', '1', 'b'*64)
    repo.register_rule(rule)
    repo.register_observation_relation(ObservationRelation.create(a.observation_id, b.observation_id,
                                        'replaces', rule_id=rule.rule_id))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('DELETE FROM rules WHERE rule_id=?', (rule.rule_id,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('UPDATE rules SET rule_id=? WHERE rule_id=?', (unknown, rule.rule_id))


@pytest.mark.parametrize('table,source,target', [
    ('document_relations', 'source_document_id', 'target_document_id'),
    ('observation_relations', 'source_observation_id', 'target_observation_id'),
])
def test_sql_rejects_self_and_noncanonical_symmetric_relations(store, table, source, target):
    repo, conn, _ = store
    da, _, a = unit(store, 'a')
    db, _, b = unit(store, 'b')
    if table == 'document_relations':
        rel = DocumentRelation.create(da.document_id, db.document_id, 'duplicate_of', reason_code='test')
        repo.register_document_relation(rel)
        assert repo.register_document_relation(DocumentRelation.create(db.document_id, da.document_id, 'duplicate_of', reason_code='test')) == WriteOutcome.IDENTICAL
    else:
        relation = ObservationRelation.create(a.observation_id, b.observation_id, 'complements', reason_code='test')
        repo.register_observation_relation(relation)
        assert repo.register_observation_relation(ObservationRelation.create(b.observation_id, a.observation_id, 'complements', reason_code='test')) == WriteOutcome.IDENTICAL
    assert conn.execute(f'SELECT count(*) FROM {table}').fetchone() == (1,)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'UPDATE {table} SET {target}={source}')
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f'UPDATE {table} SET {source}={target}, {target}={source}')



def test_multiple_source_versions_inside_one_assessment_remain_ambiguous(store):
    repo, _, _ = store
    doc, a, _ = unit(store, 'a', segment='v1', eligibility='evidence_only')
    _, b, _ = unit(store, 'b', doc=doc, segment='v2', eligibility='evidence_only')
    facts = tuple(repo.get_fact(i.fact_id) for ass in (a, b) for i in ass.inputs)
    assessment = Assessment.from_facts(doc.document_id, a.rule_id, facts, 'usable')
    repo.register_assessment(assessment)
    obs = EconomicObservation(observation_id=observation_id(assessment.assessment_id, 'combined'),
        assessment_id=assessment.assessment_id, observation_key='combined', magnitude='synthetic',
        value=facts[0].value, economic_status='usable', eligibility='candidate')
    repo.register_observation(obs, tuple(f.fact_id for f in facts))
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(obs.observation_id).reason_code == 'provenance.multiple_versions'


def test_selection_read_only_reopen_and_relation_roundtrip(store, tmp_path):
    repo, conn, _ = store
    _, _, a = unit(store, 'a')
    _, _, b = unit(store, 'b')
    relation = ObservationRelation.create(a.observation_id, b.observation_id, 'replaces', reason_code='explicit.replacement')
    repo.register_observation_relation(relation)
    path = tmp_path / 'synthetic.sqlite'
    with open_database(path, mode='create') as db:
        conn.backup(db.connection)
    before = path.read_bytes()
    with open_database(path) as db:
        reader = RelationRepository(db.connection)
        assert reader.get_observation_relation(relation.relation_id) == relation
        assert [item.observation for item in select_candidates(reader).candidates] == [a]
        assert db.connection.total_changes == 0
    assert path.read_bytes() == before


def test_competing_document_successors_are_not_automatically_admitted(store):
    repo, _, _ = store
    old, _, _ = unit(store, 'old')
    a, _, a_obs = unit(store, 'a')
    b, _, b_obs = unit(store, 'b')
    for source in (a, b):
        repo.register_document_relation(DocumentRelation.create(source.document_id, old.document_id,
                                            'supersedes', reason_code='explicit.replacement'))
    result = select_candidates(repo)
    assert not result.candidates
    assert result.decision(a_obs.observation_id).status == 'ambiguous'
    assert result.decision(b_obs.observation_id).status == 'ambiguous'
