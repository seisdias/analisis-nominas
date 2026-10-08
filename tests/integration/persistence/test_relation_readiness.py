"""Conservative relational diagnostics on loader-owned synthetic snapshots."""
from dataclasses import FrozenInstanceError, replace
from typing import Any
from uuid import UUID

import pytest

from src.canonical.certification import CertificationRequirements, EconomicEligibility
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
from src.canonical.readiness import CandidacyReadiness
from src.canonical.relation_readiness import RelationalStatus, SnapshotIntegrity
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.persistence import open_database
from src.persistence.relations import RelationRepository
from src.relation_readiness import RelationAwareReadinessEvaluator

STAMP = '2026-01-01T00:00:00Z'


def unit(repo, key, *, eligibility='evidence_only', doc=None):
    p = Person(person_id(UUID(int=1)), 'synthetic', STAMP)
    c = Corpus(corpus_id(UUID(int=2)), p.person_id, 'synthetic', 'v1', STAMP)
    repo.register_person(p)
    repo.register_corpus(c)
    if doc is None:
        doc = LogicalDocument(document_id(c.corpus_id, key), c.corpus_id, None, 'synthetic', key, STAMP)
        repo.register_document(doc)
    f = SourceFile(source_file_id('a'*64), 'a'*64, 1, 'application/pdf', created_at=STAMP)
    repo.register_source_file(f)
    v = DocumentVersion(version_id(doc.document_id, f.file_id, key), doc.document_id, f.file_id, key, STAMP)
    repo.register_version(v)
    e = Extraction(extraction_id(v.version_id, 'test', '1', 'b'*64), v.version_id, 'test', '1', 'b'*64, 'c'*64, STAMP)
    repo.register_extraction(e)
    fact = DocumentaryFact.from_draft(e.extraction_id, FactDraft('nomina.total_devengado',
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0))), created_at=STAMP)
    repo.register_fact(fact)
    r = Rule.define('test', 'direct', '1', 'a'*64, created_at=STAMP)
    repo.register_rule(r)
    a = Assessment.from_facts(doc.document_id, r.rule_id, (fact,), 'usable', created_at=STAMP)
    repo.register_assessment(a)
    o = EconomicObservation(observation_id=observation_id(a.assessment_id, 'gross'), assessment_id=a.assessment_id,
        observation_key='gross', magnitude='documentary_gross', value=fact.value, economic_status='usable',
        eligibility=eligibility, created_at=STAMP)
    repo.register_observation(o, (fact.fact_id,))
    return doc, o


@pytest.fixture
def store(tmp_path):
    path = tmp_path/'test.sqlite'
    with open_database(path, mode='create') as db:
        yield path, RelationRepository(db.connection), db.connection


def relate(repo, a, b, kind, *, document=False):
    if document:
        repo.register_document_relation(DocumentRelation.create(a.document_id, b.document_id, kind,
            reason_code='synthetic.link', created_at=STAMP))
    else:
        repo.register_observation_relation(ObservationRelation.create(a.observation_id, b.observation_id, kind,
            reason_code='synthetic.link', created_at=STAMP))


def test_no_relations_local_ready_is_not_authorization(store):
    path, repo, _ = store
    _, obs = unit(repo, 'a')
    before = path.read_bytes()
    result = RelationAwareReadinessEvaluator(path).evaluate(obs.observation_id)
    assert result.local is not None
    assert result.local.readiness is CandidacyReadiness.READY
    assert result.persisted_eligibility is EconomicEligibility.EVIDENCE_ONLY
    assert result.snapshot_integrity is SnapshotIntegrity.VERIFIED
    assert result.relational_status is RelationalStatus.CONTEXT_ONLY
    assert result == RelationAwareReadinessEvaluator(path).evaluate(obs.observation_id)
    assert not hasattr(result, 'additive')
    assert path.read_bytes() == before
    with pytest.raises(FrozenInstanceError):
        setattr(result, 'relational_status', RelationalStatus.DISPLACED)


@pytest.mark.parametrize('document', [False, True])
@pytest.mark.parametrize('eligibility', ['candidate', 'evidence_only', 'excluded'])
def test_displacement_never_reactivates_target(store, document, eligibility):
    path, repo, _ = store
    da, a = unit(repo, 'a', eligibility=eligibility)
    db, b = unit(repo, 'b')
    relate(repo, da if document else a, db if document else b,
           'supersedes' if document else 'replaces', document=document)
    result = RelationAwareReadinessEvaluator(path).evaluate(b.observation_id)
    assert result.relational_status is RelationalStatus.DISPLACED
    assert result.persisted_eligibility is EconomicEligibility.EVIDENCE_ONLY


@pytest.mark.parametrize('document', [False, True])
def test_competitors_remain_unresolved(store, document):
    path, repo, _ = store
    units = [unit(repo, k) for k in ('a', 'b', 'c')]
    for index in (0, 2):
        relate(repo, units[index][0 if document else 1], units[1][0 if document else 1],
               'supersedes' if document else 'replaces', document=document)
    for index in (0, 2):
        result = RelationAwareReadinessEvaluator(path).evaluate(units[index][1].observation_id)
        assert result.relational_status is RelationalStatus.NOT_EVALUATED
        assert any(d.reason.value == 'relations.competing_sources_unresolved' for d in result.diagnostics)


@pytest.mark.parametrize('kind', ['duplicate_of', 'same_logical_unit_pending_reconciliation'])
def test_symmetric_uncertainty_without_representative(store, kind):
    path, repo, _ = store
    da, a = unit(repo, 'a')
    db, b = unit(repo, 'b')
    relate(repo, da, db, kind, document=True)
    for obs in (a, b):
        assert RelationAwareReadinessEvaluator(path).evaluate(obs.observation_id).relational_status is RelationalStatus.UNRESOLVED


@pytest.mark.parametrize('kind,document', [('contained_in', False), ('adjusts', False),
                                           ('complements', False), ('complements', True)])
def test_context_does_not_block_or_promote(store, kind, document):
    path, repo, _ = store
    da, a = unit(repo, 'a')
    db, b = unit(repo, 'b')
    relate(repo, da if document else a, db if document else b, kind, document=document)
    result = RelationAwareReadinessEvaluator(path).evaluate(a.observation_id)
    assert result.relational_status is RelationalStatus.CONTEXT_ONLY
    assert result.local is not None
    assert result.local.readiness is CandidacyReadiness.READY
    assert result.persisted_eligibility is EconomicEligibility.EVIDENCE_ONLY


def test_cycle_and_chain_no_winner(store):
    path, repo, _ = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    _, c = unit(repo, 'c')
    for source, target in ((a,b), (b,c), (c,a)):
        relate(repo, source, target, 'replaces')
    for obs in (a,b,c):
        assert RelationAwareReadinessEvaluator(path).evaluate(obs.observation_id).relational_status is RelationalStatus.DISPLACED


def test_duplicate_with_supersession_is_not_a_new_precedence_rule(store):
    path, repo, _ = store
    da, a = unit(repo, 'a')
    db, b = unit(repo, 'b')
    relate(repo, da, db, 'duplicate_of', document=True)
    relate(repo, da, db, 'supersedes', document=True)
    result = RelationAwareReadinessEvaluator(path).evaluate(a.observation_id)
    assert result.relational_status is RelationalStatus.NOT_EVALUATED
    assert any(d.reason.value == 'relations.precedence_unresolved' for d in result.diagnostics)


def test_invalid_snapshot_is_not_evaluated(store):
    path, repo, conn = store
    _, a = unit(repo, 'a')
    conn.execute('DELETE FROM observation_facts')
    result = RelationAwareReadinessEvaluator(path).evaluate(a.observation_id)
    assert result.snapshot_integrity is SnapshotIntegrity.UNAVAILABLE
    assert result.relational_status is RelationalStatus.NOT_EVALUATED
    assert result.local is None


def test_order_independent_and_truncated_snapshot_fails_closed(store):
    from src.candidacy_snapshot import CandidacySnapshotLoader
    from src.relation_readiness import _evaluate_loaded
    path, repo, _ = store
    da, a = unit(repo, 'a')
    db, b = unit(repo, 'b')
    relate(repo, da, db, 'complements', document=True)
    snapshot = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    args = CertificationRequirements()
    assert _evaluate_loaded(snapshot, args) == _evaluate_loaded(replace(snapshot,
        observations=tuple(reversed(snapshot.observations)), facts=tuple(reversed(snapshot.facts))), args)
    result = _evaluate_loaded(replace(snapshot, documents=()), args)
    assert result.snapshot_integrity is SnapshotIntegrity.INVALID
    assert result.relational_status is RelationalStatus.NOT_EVALUATED


def test_chain_keeps_intermediate_destinations_displaced(store):
    path, repo, _ = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    _, c = unit(repo, 'c')
    relate(repo, a, b, 'replaces')
    relate(repo, b, c, 'replaces')
    for obs in (b, c):
        assert RelationAwareReadinessEvaluator(path).evaluate(obs.observation_id).relational_status is RelationalStatus.DISPLACED
    assert RelationAwareReadinessEvaluator(path).evaluate(a.observation_id).persisted_eligibility is EconomicEligibility.EVIDENCE_ONLY


def test_local_context_failure_is_separate_from_relations(store):
    path, repo, _ = store
    _, a = unit(repo, 'a', eligibility='candidate')
    result = RelationAwareReadinessEvaluator(path).evaluate(a.observation_id,
        requirements=CertificationRequirements(currency=True))
    assert result.local is not None
    assert result.local.readiness is CandidacyReadiness.BLOCKED
    assert result.relational_status is RelationalStatus.CONTEXT_ONLY
    assert result.persisted_eligibility is EconomicEligibility.CANDIDATE


def test_sibling_interpretations_are_not_automatically_selected(store):
    path, repo, _ = store
    doc, a = unit(repo, 'a')
    unit(repo, 'b', doc=doc)
    result = RelationAwareReadinessEvaluator(path).evaluate(a.observation_id)
    assert result.relational_status is RelationalStatus.NOT_EVALUATED
    assert any(d.reason.value == 'relations.interpretations_unresolved' for d in result.diagnostics)


def test_all_collection_orders_irrelevant_for_competing_chain(store):
    from dataclasses import fields

    from src.candidacy_snapshot import CandidacySnapshotLoader
    from src.relation_readiness import _evaluate_loaded
    path, repo, _ = store
    _, a = unit(repo, 'a')
    _, b = unit(repo, 'b')
    _, c = unit(repo, 'c')
    relate(repo, a, b, 'replaces')
    relate(repo, c, b, 'replaces')
    snapshot = CandidacySnapshotLoader(path).load_candidacy_snapshot(a.observation_id)
    changes: dict[str, Any] = {f.name: tuple(reversed(getattr(snapshot, f.name)))
        for f in fields(snapshot) if isinstance(getattr(snapshot, f.name), tuple)}
    shuffled = replace(snapshot, **changes)
    assert _evaluate_loaded(snapshot, CertificationRequirements()) == _evaluate_loaded(shuffled, CertificationRequirements())
