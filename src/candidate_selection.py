"""Conservative read-only candidate selection, without aggregation or graph resolution."""

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from typing import Protocol

from src.canonical.economics import Assessment, ObservationEvidence
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.canonical.values import ExactDecimal, ValueState


class CandidateRepository(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...
    def list_assessments(self) -> tuple[Assessment, ...]: ...
    def get_observations(self, assessment_id: str) -> tuple[ObservationEvidence, ...]: ...
    def candidate_versions(self, assessment: Assessment, evidence: ObservationEvidence) -> tuple[str, ...]: ...
    def list_document_relations(self) -> tuple[DocumentRelation, ...]: ...
    def list_observation_relations(self) -> tuple[ObservationRelation, ...]: ...


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    evidence: ObservationEvidence
    status: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class CandidateSelection:
    decisions: tuple[CandidateDecision, ...]

    @property
    def candidates(self) -> tuple[ObservationEvidence, ...]:
        return tuple(d.evidence for d in self.decisions if d.status == 'candidate')

    def decision(self, observation_id: str) -> CandidateDecision:
        for decision in self.decisions:
            if decision.evidence.observation.observation_id == observation_id:
                return decision
        raise KeyError(observation_id)


def _deferred(status: str) -> str:
    return status if status in ('ambiguous', 'excluded') else 'pending'


def _admissibility(repo: CandidateRepository, assessment: Assessment,
                   evidence: ObservationEvidence) -> CandidateDecision:
    obs = evidence.observation
    if assessment.status != 'usable':
        return CandidateDecision(evidence, _deferred(assessment.status), 'assessment.' + assessment.status)
    if obs.economic_status != 'usable':
        return CandidateDecision(evidence, _deferred(obs.economic_status), 'economic.' + obs.economic_status)
    if obs.eligibility != 'candidate':
        return CandidateDecision(evidence, 'excluded', 'eligibility.' + obs.eligibility)
    if obs.value.state != ValueState.PRESENT or type(obs.value.value) is not ExactDecimal:
        return CandidateDecision(evidence, 'pending', 'value.not_usable')
    try:
        versions = repo.candidate_versions(assessment, evidence)
    except ValueError:
        return CandidateDecision(evidence, 'pending', 'provenance.not_verified')
    if not versions:
        return CandidateDecision(evidence, 'pending', 'provenance.not_verified')
    if len(versions) != 1:
        return CandidateDecision(evidence, 'ambiguous', 'provenance.multiple_versions')
    return CandidateDecision(evidence, 'candidate', 'admissible.explicit_candidate')


def select_candidates(repository: CandidateRepository) -> CandidateSelection:
    """Read the complete stored set under one snapshot; never mark an assessment active.

    An explicit replacement suppresses its target without fallback if its source
    is inadmissible. Non-replacement observation relations do not remove either
    side. Returned candidates are proposals, not instructions to add their values.
    """
    with repository.transaction():
        assessments = {a.assessment_id: a for a in repository.list_assessments()}
        decisions = {
            e.observation.observation_id: _admissibility(repository, a, e)
            for a in assessments.values() for e in repository.get_observations(a.assessment_id)
        }
        by_document: dict[str, list[str]] = {}
        for identity, decision in decisions.items():
            document = assessments[decision.evidence.observation.assessment_id].document_id
            by_document.setdefault(document, []).append(identity)

        def block(identity: str, status: str, reason: str) -> None:
            if identity in decisions and decisions[identity].status == 'candidate':
                decisions[identity] = replace(decisions[identity], status=status, reason_code=reason)

        document_relations = repository.list_document_relations()
        superseded = {r.target_document_id for r in document_relations if r.relation_type == 'supersedes'}
        for document in superseded:
            for identity in by_document.get(document, []):
                block(identity, 'excluded', 'document.superseded')
        for relation in document_relations:
            if relation.relation_type in ('duplicate_of', 'same_logical_unit_pending_reconciliation'):
                # Explicit supersession already disqualifies one side; no symmetric
                # edge is itself allowed to designate a preferred representative.
                if relation.source_document_id in superseded or relation.target_document_id in superseded:
                    continue
                status = 'ambiguous' if relation.relation_type == 'duplicate_of' else 'pending'
                for document in (relation.source_document_id, relation.target_document_id):
                    for identity in by_document.get(document, []):
                        block(identity, status, 'document.' + relation.relation_type)

        successors: dict[str, set[str]] = {}
        for relation in document_relations:
            if relation.relation_type == 'supersedes':
                successors.setdefault(relation.target_document_id, set()).add(relation.source_document_id)
        disputed_documents = set()
        for sources in successors.values():
            admissible_sources = [d for d in sources
                                  if any(decisions[i].status == 'candidate' for i in by_document.get(d, []))]
            if len(admissible_sources) > 1:
                disputed_documents.update(admissible_sources)
        for document in disputed_documents:
            for identity in by_document.get(document, []):
                block(identity, 'ambiguous', 'document.competing_successors')

        replacements: dict[str, set[str]] = {}
        for observation_relation in repository.list_observation_relations():
            if observation_relation.relation_type == 'replaces':
                block(observation_relation.target_observation_id, 'excluded', 'observation.replaced')
                replacements.setdefault(observation_relation.target_observation_id, set()).add(observation_relation.source_observation_id)
        # Collect all disputes before applying any deferral: otherwise overlapping
        # replacement assertions could accidentally favor the last visited source.
        disputed = set()
        for sources in replacements.values():
            admissible = [s for s in sources if s in decisions and decisions[s].status == 'candidate']
            if len(admissible) > 1:
                disputed.update(admissible)
        for identity in disputed:
            block(identity, 'ambiguous', 'replacement.competing_sources')

        # V5 has no active-assessment pointer. Do not pick among remaining usable
        # candidate-producing assessments of one logical document by date or order.
        for identities in by_document.values():
            remaining = [i for i in identities if decisions[i].status == 'candidate']
            competing = {decisions[i].evidence.observation.assessment_id for i in remaining}
            if len(competing) > 1:
                for identity in remaining:
                    block(identity, 'ambiguous', 'assessment.competing_interpretations')
        return CandidateSelection(tuple(decisions[i] for i in sorted(decisions)))
