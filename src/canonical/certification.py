"""Local documentary-value certification, not selection or permission to aggregate.

Inputs are a snapshot of T6 records loaded through its validated repositories.
This pure evaluator checks their links and assessment fingerprints; it does not
re-read PDFs, authenticate extraction output, or certify literal printed values.
Certification means faithful support in the normalized documentary evidence.
No relation resolution, arithmetic, persistence or eligibility promotion occurs.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from src.canonical.documents import DocumentVersion, Extraction, LogicalDocument
from src.canonical.economics import Assessment, ObservationEvidence, Rule, fact_fingerprint
from src.canonical.facts import DocumentaryFact
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState


class EconomicEligibility(StrEnum):
    CANDIDATE = 'candidate'
    EVIDENCE_ONLY = 'evidence_only'
    EXCLUDED = 'excluded'


class CertificationStatus(StrEnum):
    CERTIFIED = 'certified'
    BLOCKED = 'blocked'


class CertificationReason(StrEnum):
    PROVENANCE_INSUFFICIENT = 'provenance.insufficient'
    VALUE_UNUSABLE = 'value.unusable'
    UNSUPPORTED_MAGNITUDE = 'magnitude.unsupported'
    SUPPORT_MISMATCH = 'support.mismatch'
    ASSESSMENT_UNUSABLE = 'assessment.unusable'
    OBSERVATION_UNUSABLE = 'observation.unusable'
    CURRENCY_UNKNOWN = 'context.currency_unknown'
    EMPLOYER_UNKNOWN = 'context.employer_unknown'
    LIQUIDATION_UNKNOWN = 'context.liquidation_unknown'
    ACCRUAL_UNKNOWN = 'context.accrual_unknown'
    PAYMENT_UNKNOWN = 'context.payment_unknown'


@dataclass(frozen=True, slots=True)
class CertificationRequirements:
    """Explicit requirements of a requested use, never inferred from payroll month."""
    currency: bool = False
    employer: bool = False
    liquidation_period: bool = False
    accrual_interval: bool = False
    payment_date: bool = False

    def __post_init__(self) -> None:
        if any(type(v) is not bool for v in (self.currency, self.employer,
               self.liquidation_period, self.accrual_interval, self.payment_date)):
            raise TypeError('Requirements must be explicit booleans')


@dataclass(frozen=True, slots=True)
class DocumentarySupport:
    """One source version and the complete assessment input manifest.

    Unknown exact fact pages are allowed; document/version scope is sufficient.
    Ownership/existence of physical files remains the T6 repository boundary.
    """
    document: LogicalDocument
    version: DocumentVersion
    extraction: Extraction
    rule: Rule
    assessment: Assessment
    facts: tuple[DocumentaryFact, ...]


@dataclass(frozen=True, slots=True)
class EconomicCertification:
    observation_id: str
    value: CanonicalValue
    eligibility: EconomicEligibility
    requirements: CertificationRequirements
    value_reasons: tuple[CertificationReason, ...]
    context_reasons: tuple[CertificationReason, ...]
    contract: Literal['economic-certification/v1'] = 'economic-certification/v1'

    @property
    def value_status(self) -> CertificationStatus:
        return CertificationStatus.BLOCKED if self.value_reasons else CertificationStatus.CERTIFIED

    @property
    def context_satisfied(self) -> bool:
        """Context only; not value certification, candidacy or additivity."""
        return not self.context_reasons


def _supported(evidence: ObservationEvidence, support: DocumentarySupport) -> bool:
    a = support.assessment
    facts = {f.fact_id: f for f in support.facts}
    return (
        evidence.observation.assessment_id == a.assessment_id
        and a.rule_id == support.rule.rule_id
        and a.document_id == support.document.document_id == support.version.document_id
        and support.extraction.version_id == support.version.version_id
        and len(facts) == len(support.facts)
        and set(facts) == {i.fact_id for i in a.inputs}
        and bool(evidence.fact_ids)
        and set(evidence.fact_ids) <= facts.keys()
        and all(f.extraction_id == support.extraction.extraction_id for f in facts.values())
        and all(fact_fingerprint(facts[i.fact_id]) == i.content_hash for i in a.inputs)
    )


def certify_observation(
    evidence: ObservationEvidence,
    support: DocumentarySupport,
    requirements: CertificationRequirements = CertificationRequirements(),
) -> EconomicCertification:
    """Certify only a directly supported gross/net value in the supplied snapshot.

    Existing eligibility is reported unchanged, never granted. Requirements can
    block a contextual use independently of the documentary-value certificate.
    Relation-aware candidacy remains outside this function (including ALTEN).
    """
    obs = evidence.observation
    reasons: list[CertificationReason] = []
    context: list[CertificationReason] = []
    targets = {'documentary_gross': 'nomina.total_devengado',
               'documentary_net': 'nomina.liquido_percibir'}
    key = targets.get(obs.magnitude)
    if key is None:
        reasons.append(CertificationReason.UNSUPPORTED_MAGNITUDE)
    if obs.value.state != ValueState.PRESENT or type(obs.value.value) is not ExactDecimal:
        reasons.append(CertificationReason.VALUE_UNUSABLE)
    if support.assessment.status != 'usable':
        reasons.append(CertificationReason.ASSESSMENT_UNUSABLE)
    if obs.economic_status != 'usable':
        reasons.append(CertificationReason.OBSERVATION_UNUSABLE)
    if not _supported(evidence, support):
        reasons.append(CertificationReason.PROVENANCE_INSUFFICIENT)
    elif key is not None:
        facts = {f.fact_id: f for f in support.facts}
        if (len(evidence.fact_ids) != 1 or obs.scope != 'total'
                or obs.confidence not in ('explicit', 'mapped')
                or facts[evidence.fact_ids[0]].fact_key != key
                or facts[evidence.fact_ids[0]].value != obs.value):
            reasons.append(CertificationReason.SUPPORT_MISMATCH)
    for required, known, reason in (
        (requirements.currency, obs.value.currency is not None, CertificationReason.CURRENCY_UNKNOWN),
        (requirements.employer, support.document.employer_id is not None, CertificationReason.EMPLOYER_UNKNOWN),
        (requirements.liquidation_period, obs.liquidation_period.state == ValueState.PRESENT,
         CertificationReason.LIQUIDATION_UNKNOWN),
        (requirements.accrual_interval, obs.accrual.state == ValueState.PRESENT,
         CertificationReason.ACCRUAL_UNKNOWN),
        (requirements.payment_date, obs.payment_date.state == ValueState.PRESENT,
         CertificationReason.PAYMENT_UNKNOWN),
    ):
        if required and not known:
            context.append(reason)
    eligibility = EconomicEligibility(obs.eligibility)
    return EconomicCertification(obs.observation_id, obs.value, eligibility, requirements,
                                 tuple(reasons), tuple(context))
