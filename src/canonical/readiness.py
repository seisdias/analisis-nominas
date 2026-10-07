"""Local candidacy readiness, never candidate authorization or relation resolution."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from src.canonical.certification import (
    CertificationRequirements,
    CertificationStatus,
    DocumentarySupport,
    EconomicCertification,
    EconomicEligibility,
    certify_observation,
)
from src.canonical.economics import ObservationEvidence


class CandidacyReadiness(StrEnum):
    READY = 'ready'
    BLOCKED = 'blocked'
    NOT_EVALUATED = 'not_evaluated'


class CandidacyReason(StrEnum):
    ELIGIBILITY_EXCLUDED = 'eligibility.excluded'
    CERTIFICATION_BLOCKED = 'certification.blocked'
    CONTEXT_REQUIREMENTS_UNSATISFIED = 'context.requirements_unsatisfied'
    RELATIONAL_SNAPSHOT_INCOMPLETE = 'context.relational_snapshot_incomplete'


@dataclass(frozen=True, slots=True)
class CandidacyContext:
    """Caller declares completeness, not absence of conflicts or economic approval.

    No relation collection is consumed or interpreted in this increment. A complete
    snapshot can be empty or nonempty: READY only describes these local checks,
    never the outcome of relation-aware selection. Defaults fail closed. Disabling
    the relational requirement must be explicit and remains visible in the result.
    """
    relational_context_required: bool = True
    relational_snapshot_complete: bool = False

    def __post_init__(self) -> None:
        if (type(self.relational_context_required) is not bool
                or type(self.relational_snapshot_complete) is not bool):
            raise TypeError('Context completeness and requirement must be explicit booleans')


@dataclass(frozen=True, slots=True)
class CandidacyEvaluation:
    observation_id: str
    persisted_eligibility: EconomicEligibility
    certification: EconomicCertification
    readiness: CandidacyReadiness
    reasons: tuple[CandidacyReason, ...]
    context: CandidacyContext
    contract: Literal['candidacy-readiness/v1'] = 'candidacy-readiness/v1'


def evaluate_candidacy_readiness(
    evidence: ObservationEvidence,
    support: DocumentarySupport,
    *,
    requirements: CertificationRequirements = CertificationRequirements(),
    context: CandidacyContext = CandidacyContext(),
) -> CandidacyEvaluation:
    """Recompute certification from this snapshot; never accept an external certificate.

    Detailed value/context failure reasons remain in the embedded certification;
    they are not reimplemented or translated into new economic policy. Required
    incomplete context takes precedence over BLOCKED, retaining all known blockers.
    Completeness is an explicit caller assertion, not verified by a pure function.
    No eligibility is promoted and no relation is resolved, even for READY.
    """
    if type(context) is not CandidacyContext or type(requirements) is not CertificationRequirements:
        raise TypeError('Typed context and certification requirements required')
    certification = certify_observation(evidence, support, requirements)
    reasons = []
    if certification.eligibility is EconomicEligibility.EXCLUDED:
        reasons.append(CandidacyReason.ELIGIBILITY_EXCLUDED)
    if certification.value_status is not CertificationStatus.CERTIFIED:
        reasons.append(CandidacyReason.CERTIFICATION_BLOCKED)
    if not certification.context_satisfied:
        reasons.append(CandidacyReason.CONTEXT_REQUIREMENTS_UNSATISFIED)
    incomplete = context.relational_context_required and not context.relational_snapshot_complete
    if incomplete:
        reasons.append(CandidacyReason.RELATIONAL_SNAPSHOT_INCOMPLETE)
    readiness = (CandidacyReadiness.NOT_EVALUATED if incomplete else
                 CandidacyReadiness.BLOCKED if reasons else CandidacyReadiness.READY)
    return CandidacyEvaluation(evidence.observation.observation_id, certification.eligibility,
                              certification, readiness, tuple(sorted(reasons, key=lambda r: r.value)),
                              context)
