"""Versioned interpretations, independent of payroll models and storage."""

from dataclasses import dataclass, field
from datetime import date

from src.canonical.evidence import _id, _sha, _text, _time, utc_now
from src.canonical.facts import DocumentaryFact
from src.canonical.identifiers import CanonicalId
from src.canonical.serialization import canonical_sha256, deterministic_id
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState

STATUSES = ('usable', 'pending', 'ambiguous', 'excluded', 'incomplete')


def rule_id(family: str, name: str, version: str, implementation_hash: str) -> CanonicalId:
    for text in (family, name, version):
        _text(text)
    _sha(implementation_hash)
    return deterministic_id('rule', {'family': family, 'name': name, 'version': version,
                                     'implementation_hash': implementation_hash})


def assessment_id(document_id: str, rule_id: str, input_signature: str) -> CanonicalId:
    _id(document_id, 'document')
    _id(rule_id, 'rule')
    _sha(input_signature)
    return deterministic_id('assessment', {'document_id': str(document_id), 'rule_id': str(rule_id),
                                           'input_signature': input_signature})


def observation_id(assessment_id: str, observation_key: str) -> CanonicalId:
    _id(assessment_id, 'assessment')
    _text(observation_key)
    return deterministic_id('observation', {'assessment_id': str(assessment_id),
                                            'observation_key': observation_key})


def fact_fingerprint(fact: DocumentaryFact) -> str:
    return canonical_sha256({'extraction_id': str(fact.extraction_id), 'fact_key': fact.fact_key,
                             'value': fact.value})


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    family: str
    name: str
    version: str
    implementation_hash: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.rule_id != rule_id(self.family, self.name, self.version, self.implementation_hash):
            raise ValueError('Rule identity does not match definition')
        _time(self.created_at)

    @classmethod
    def define(cls, family: str, name: str, version: str, implementation_hash: str, *,
               created_at: str | None = None) -> 'Rule':
        return cls(rule_id(family, name, version, implementation_hash), family, name, version,
                   implementation_hash, utc_now() if created_at is None else created_at)


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    fact_id: str
    content_hash: str

    def __post_init__(self) -> None:
        _id(self.fact_id, 'fact')
        _sha(self.content_hash)


def input_manifest(inputs: tuple[AssessmentInput, ...]) -> list[dict[str, str]]:
    return [{'fact_id': str(item.fact_id), 'content_hash': item.content_hash} for item in inputs]


@dataclass(frozen=True, slots=True)
class Assessment:
    assessment_id: str
    document_id: str
    rule_id: str
    input_signature: str
    inputs: tuple[AssessmentInput, ...]
    status: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if type(self.inputs) is not tuple or any(type(i) is not AssessmentInput for i in self.inputs):
            raise TypeError('Immutable typed input manifest required')
        ids = [i.fact_id for i in self.inputs]
        if ids != sorted(set(ids)):
            raise ValueError('Assessment inputs must be sorted and unique')
        if canonical_sha256(input_manifest(self.inputs)) != self.input_signature:
            raise ValueError('Input signature mismatch')
        if self.assessment_id != assessment_id(self.document_id, self.rule_id, self.input_signature):
            raise ValueError('Assessment identity mismatch')
        if self.status not in STATUSES or (self.status == 'usable' and not self.inputs):
            raise ValueError('Invalid assessment status/inputs')
        _time(self.created_at)

    @classmethod
    def from_facts(cls, document_id: str, rule_id: str, facts: tuple[DocumentaryFact, ...],
                   status: str, *, created_at: str | None = None) -> 'Assessment':
        inputs = tuple(sorted((AssessmentInput(f.fact_id, fact_fingerprint(f)) for f in facts),
                              key=lambda item: item.fact_id))
        signature = canonical_sha256(input_manifest(inputs))
        return cls(assessment_id(document_id, rule_id, signature), document_id, rule_id,
                   signature, inputs, status, utc_now() if created_at is None else created_at)


def _date(text: str) -> None:
    if date.fromisoformat(text).isoformat() != text:
        raise ValueError('ISO YYYY-MM-DD required')


def _temporal(value: CanonicalValue, *, month: bool = False) -> None:
    if type(value) is not CanonicalValue or value.currency is not None:
        raise ValueError('Temporal value cannot carry currency')
    if value.value is not None:
        if type(value.value) is not str:
            raise ValueError('Temporal candidate must be text')
        _date(value.value + '-01' if month else value.value)


def unknown_time() -> CanonicalValue:
    return CanonicalValue(state=ValueState.UNKNOWN)


@dataclass(frozen=True, slots=True)
class AccrualInterval:
    state: ValueState = ValueState.UNKNOWN
    start: str | None = None
    end: str | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (self.start is None) != (self.end is None):
            raise ValueError('Accrual candidate requires both endpoints')
        if self.start is not None and self.end is not None:
            _date(self.start)
            _date(self.end)
            if self.start > self.end:
                raise ValueError('Reversed accrual interval')
        CanonicalValue(state=self.state, value=self.start, reason_code=self.reason_code)


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicObservation:
    observation_id: str
    assessment_id: str
    observation_key: str
    magnitude: str
    value: CanonicalValue
    scope: str = 'total'
    nature: str = 'unknown'
    pay_behavior: str = 'unknown'
    temporal_character: str = 'unknown'
    payment_form: str = 'unknown'
    settlement_context: str = 'unknown'
    liquidation_period: CanonicalValue = field(default_factory=unknown_time)
    accrual: AccrualInterval = field(default_factory=AccrualInterval)
    payment_date: CanonicalValue = field(default_factory=unknown_time)
    economic_status: str = 'pending'
    eligibility: str = 'evidence_only'
    confidence: str = 'mapped'
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.observation_id != observation_id(self.assessment_id, self.observation_key):
            raise ValueError('Observation identity mismatch')
        for text in (self.magnitude, self.nature, self.settlement_context):
            _text(text)
        for value, allowed in (
            (self.scope, ('total', 'component', 'base', 'auxiliary')),
            (self.pay_behavior, ('fixed', 'variable', 'unknown')),
            (self.temporal_character, ('current', 'arrears', 'adjustment', 'unknown')),
            (self.payment_form, ('cash', 'in_kind', 'mixed', 'unknown')),
            (self.economic_status, STATUSES),
            (self.eligibility, ('candidate', 'evidence_only', 'excluded')),
            (self.confidence, ('explicit', 'mapped', 'reconstructed', 'inferred')),
        ):
            if value not in allowed:
                raise ValueError('Invalid economic dimension')
        if type(self.value) is not CanonicalValue:
            raise TypeError('Canonical value required')
        if self.value.value is not None and type(self.value.value) is not ExactDecimal:
            raise ValueError('Economic magnitude requires decimal or absence')
        if self.economic_status == 'usable' and self.value.state != ValueState.PRESENT:
            raise ValueError('Usable observation requires a present value')
        if self.eligibility == 'candidate' and (self.economic_status != 'usable'
                                               or self.value.state != ValueState.PRESENT):
            raise ValueError('Candidate requires usable status and present value')
        if self.economic_status == 'excluded' and self.eligibility != 'excluded':
            raise ValueError('Excluded observation cannot be eligible')
        _temporal(self.liquidation_period, month=True)
        _temporal(self.payment_date)
        if type(self.accrual) is not AccrualInterval:
            raise TypeError('Accrual interval required')
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class ObservationEvidence:
    observation: EconomicObservation
    fact_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.fact_ids or type(self.fact_ids) is not tuple:
            raise ValueError('Nonempty immutable provenance required')
        if list(self.fact_ids) != sorted(set(self.fact_ids)):
            raise ValueError('Provenance must be unique and sorted')
        for identity in self.fact_ids:
            _id(identity, 'fact')


@dataclass(frozen=True, slots=True)
class Interpretation:
    rule: Rule
    assessment: Assessment
    observations: tuple[ObservationEvidence, ...]
