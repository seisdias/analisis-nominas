"""Loader-owned read-only diagnostics; never execute or imitate T6 selection.

T6 competition depends on prior candidate filtering. Here competing assertions,
assessment alternatives and duplicate/supersession interactions remain unresolved;
no source is called admissible merely because its local T7 readiness is READY.
"""
from pathlib import Path

from src.candidacy_snapshot import CandidacySnapshotError, CandidacySnapshotLoader
from src.canonical.certification import (
    CertificationRequirements,
    DocumentarySupport,
    EconomicEligibility,
)
from src.canonical.economics import fact_fingerprint
from src.canonical.readiness import CandidacyContext, evaluate_candidacy_readiness
from src.canonical.relation_readiness import (
    RelationalDiagnostic,
    RelationalReason,
    RelationalStatus,
    RelationAwareReadinessEvaluation,
    SnapshotIntegrity,
)
from src.canonical.relational_snapshot import CandidacyRelationalSnapshot


class RelationAwareReadinessEvaluator:
    """Public entrypoint accepts a database/ID, never an asserted complete snapshot."""
    def __init__(self, database: str | Path) -> None:
        self._loader = CandidacySnapshotLoader(database)

    def evaluate(self, observation_id: str, *,
                 requirements: CertificationRequirements = CertificationRequirements(),
                 ) -> RelationAwareReadinessEvaluation:
        try:
            snapshot = self._loader.load_candidacy_snapshot(observation_id)
        except CandidacySnapshotError:
            return RelationAwareReadinessEvaluation(observation_id, None, None,
                SnapshotIntegrity.UNAVAILABLE, RelationalStatus.NOT_EVALUATED,
                (RelationalDiagnostic(RelationalReason.SNAPSHOT_UNAVAILABLE),))
        return _evaluate_loaded(snapshot, requirements)


def _validate(s: CandidacyRelationalSnapshot) -> None:
    """Structural guard, not proof of exhaustive reading (provided by the loader)."""
    if (s.contract != 'candidacy-relational-snapshot/v1'
            or s.scope != 'registered-document-observation-closure'):
        raise ValueError('Unsupported snapshot')
    observations = {o.observation.observation_id: o for o in s.observations}
    assessments = {a.assessment_id: a for a in s.assessments}
    documents = {d.document_id: d for d in s.documents}
    versions = {v.version_id: v for v in s.versions}
    extractions = {e.extraction_id: e for e in s.extractions}
    facts = {f.fact_id: f for f in s.facts}
    rules = {r.rule_id: r for r in s.rules}
    files = {f.file_id: f for f in s.source_files}
    if (len(observations) != len(s.observations) or len(assessments) != len(s.assessments)
            or len(documents) != len(s.documents) or len(versions) != len(s.versions)
            or len(extractions) != len(s.extractions) or len(facts) != len(s.facts)
            or observations.get(s.target.observation.observation_id) != s.target):
        raise ValueError('Inconsistent records')
    for v in versions.values():
        documents[v.document_id]
        files[v.file_id]
    for e in extractions.values():
        versions[e.version_id]
    for a in assessments.values():
        documents[a.document_id]
        rules[a.rule_id]
        for i in a.inputs:
            f = facts[i.fact_id]
            if (fact_fingerprint(f) != i.content_hash
                    or versions[extractions[f.extraction_id].version_id].document_id != a.document_id):
                raise ValueError('Invalid assessment support')
    for o in observations.values():
        a = assessments[o.observation.assessment_id]
        if not o.fact_ids or not set(o.fact_ids) <= {i.fact_id for i in a.inputs}:
            raise ValueError('Invalid observation support')
    for dr in s.document_relations:
        documents[dr.source_document_id]
        documents[dr.target_document_id]
        if dr.rule_id is not None:
            rules[dr.rule_id]
    for relation in s.observation_relations:
        observations[relation.source_observation_id]
        observations[relation.target_observation_id]
        if relation.rule_id is not None:
            rules[relation.rule_id]


def _evaluate_loaded(s: CandidacyRelationalSnapshot,
                     requirements: CertificationRequirements) -> RelationAwareReadinessEvaluation:
    """Internal pure evaluation; only the public loader entrypoint attests completeness."""
    obs = s.target.observation
    try:
        _validate(s)
    except (ValueError, KeyError, TypeError):
        return RelationAwareReadinessEvaluation(obs.observation_id, None, None,
            SnapshotIntegrity.INVALID, RelationalStatus.NOT_EVALUATED,
            (RelationalDiagnostic(RelationalReason.SNAPSHOT_INVALID),))
    assessments = {a.assessment_id: a for a in s.assessments}
    assessment = assessments[obs.assessment_id]
    document = next(d for d in s.documents if d.document_id == assessment.document_id)
    facts = tuple(sorted((f for f in s.facts if f.fact_id in {i.fact_id for i in assessment.inputs}),
                         key=lambda f: f.fact_id))
    diagnostics = set()
    local = None
    extraction_ids = {f.extraction_id for f in facts}
    if len(extraction_ids) == 1:
        extraction = next(e for e in s.extractions if e.extraction_id in extraction_ids)
        version = next(v for v in s.versions if v.version_id == extraction.version_id)
        rule = next(r for r in s.rules if r.rule_id == assessment.rule_id)
        local = evaluate_candidacy_readiness(s.target, DocumentarySupport(
            document, version, extraction, rule, assessment, facts), requirements=requirements,
            context=CandidacyContext(relational_snapshot_complete=True))
    else:
        diagnostics.add(RelationalDiagnostic(RelationalReason.LOCAL_SUPPORT_UNSUPPORTED))
    displaced = False
    unresolved = False
    deferred = local is None
    superseded = {r.target_document_id for r in s.document_relations if r.relation_type == 'supersedes'}
    doc_sources: dict[str, list[tuple[str, str]]] = {}
    obs_sources: dict[str, list[tuple[str, str]]] = {}
    for r in s.document_relations:
        touches = document.document_id in (r.source_document_id, r.target_document_id)
        if r.relation_type == 'supersedes':
            doc_sources.setdefault(r.target_document_id, []).append((r.source_document_id, r.relation_id))
            if touches:
                diagnostics.add(RelationalDiagnostic(RelationalReason.DOCUMENT_SUPERSEDES, (r.relation_id,)))
            displaced |= document.document_id == r.target_document_id
        elif touches and r.relation_type in ('duplicate_of', 'same_logical_unit_pending_reconciliation'):
            reason = (RelationalReason.DUPLICATE if r.relation_type == 'duplicate_of'
                      else RelationalReason.RECONCILIATION)
            diagnostics.add(RelationalDiagnostic(reason, (r.relation_id,)))
            if r.source_document_id in superseded or r.target_document_id in superseded:
                # T6 skips the symmetric block after supersession; do not invent a
                # different precedence or claim that a representative is selected.
                deferred = True
                diagnostics.add(RelationalDiagnostic(RelationalReason.PRECEDENCE, (r.relation_id,)))
            else:
                unresolved = True
        elif touches:
            diagnostics.add(RelationalDiagnostic(RelationalReason.CONTEXT_RELATION, (r.relation_id,)))
    for edge in s.observation_relations:
        touches = obs.observation_id in (edge.source_observation_id, edge.target_observation_id)
        if edge.relation_type == 'replaces':
            obs_sources.setdefault(edge.target_observation_id, []).append((edge.source_observation_id, edge.relation_id))
            if touches:
                diagnostics.add(RelationalDiagnostic(RelationalReason.OBSERVATION_REPLACES, (edge.relation_id,)))
            displaced |= obs.observation_id == edge.target_observation_id
        elif touches:
            diagnostics.add(RelationalDiagnostic(RelationalReason.CONTEXT_RELATION, (edge.relation_id,)))
    for groups, target in ((doc_sources, document.document_id), (obs_sources, obs.observation_id)):
        for sources in groups.values():
            if len(sources) > 1 and target in {source for source, _ in sources}:
                deferred = True
                diagnostics.add(RelationalDiagnostic(RelationalReason.COMPETING_SOURCES,
                                                       tuple(sorted(r for _, r in sources))))
    sibling_assessments = {a.assessment_id for a in s.assessments if a.document_id == document.document_id}
    if len(sibling_assessments) > 1:
        deferred = True
        diagnostics.add(RelationalDiagnostic(RelationalReason.INTERPRETATIONS))
    status = (RelationalStatus.DISPLACED if displaced else RelationalStatus.NOT_EVALUATED if deferred
              else RelationalStatus.UNRESOLVED if unresolved else RelationalStatus.CONTEXT_ONLY)
    return RelationAwareReadinessEvaluation(obs.observation_id, EconomicEligibility(obs.eligibility),
        local, SnapshotIntegrity.VERIFIED, status,
        tuple(sorted(diagnostics, key=lambda d: (d.reason.value, d.relation_ids))))
