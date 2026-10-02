"""Two explicit relation vocabularies, not a generic graph or resolution engine."""

import re
from dataclasses import dataclass, field

from src.canonical.evidence import _id, _time, utc_now
from src.canonical.identifiers import CanonicalId
from src.canonical.serialization import deterministic_id

DOCUMENT_TYPES = ('duplicate_of', 'supersedes', 'complements', 'same_logical_unit_pending_reconciliation')
DOCUMENT_SYMMETRIC = ('duplicate_of', 'complements', 'same_logical_unit_pending_reconciliation')
OBSERVATION_TYPES = ('contained_in', 'adjusts', 'replaces', 'complements')
OBSERVATION_SYMMETRIC = ('complements',)


def _endpoints(source: str, target: str, namespace: str, symmetric: bool) -> tuple[str, str]:
    _id(source, namespace)
    _id(target, namespace)
    if source == target:
        raise ValueError('Self relations are forbidden')
    if symmetric and source > target:
        source, target = target, source
    return str(source), str(target)


def _provenance(rule_id: str | None, reason_code: str | None) -> None:
    if rule_id is None and reason_code is None:
        raise ValueError('Relation requires rule provenance or an explicit reason')
    if rule_id is not None:
        _id(rule_id, 'rule')
    if reason_code is not None and not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*', reason_code):
        raise ValueError('Reason must be a lowercase dotted identifier')


def document_relation_id(source: str, target: str, relation_type: str) -> CanonicalId:
    if relation_type not in DOCUMENT_TYPES:
        raise ValueError('Unknown document relation type')
    source, target = _endpoints(source, target, 'document', relation_type in DOCUMENT_SYMMETRIC)
    return deterministic_id('document_relation', {'source': source, 'target': target, 'type': relation_type})


def observation_relation_id(source: str, target: str, relation_type: str) -> CanonicalId:
    if relation_type not in OBSERVATION_TYPES:
        raise ValueError('Unknown observation relation type')
    source, target = _endpoints(source, target, 'observation', relation_type in OBSERVATION_SYMMETRIC)
    return deterministic_id('observation_relation', {'source': source, 'target': target, 'type': relation_type})


@dataclass(frozen=True, slots=True)
class DocumentRelation:
    relation_id: str
    source_document_id: str
    target_document_id: str
    relation_type: str
    rule_id: str | None = None
    reason_code: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        expected = document_relation_id(self.source_document_id, self.target_document_id, self.relation_type)
        if self.relation_id != expected:
            raise ValueError('Document relation identity mismatch')
        source, target = _endpoints(self.source_document_id, self.target_document_id, 'document',
                                    self.relation_type in DOCUMENT_SYMMETRIC)
        object.__setattr__(self, 'source_document_id', source)
        object.__setattr__(self, 'target_document_id', target)
        _provenance(self.rule_id, self.reason_code)
        _time(self.created_at)

    @classmethod
    def create(cls, source: str, target: str, relation_type: str, *, rule_id: str | None = None,
               reason_code: str | None = None, created_at: str | None = None) -> 'DocumentRelation':
        return cls(document_relation_id(source, target, relation_type), source, target, relation_type,
                   rule_id, reason_code, utc_now() if created_at is None else created_at)


@dataclass(frozen=True, slots=True)
class ObservationRelation:
    relation_id: str
    source_observation_id: str
    target_observation_id: str
    relation_type: str
    rule_id: str | None = None
    reason_code: str | None = None
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        expected = observation_relation_id(self.source_observation_id, self.target_observation_id, self.relation_type)
        if self.relation_id != expected:
            raise ValueError('Observation relation identity mismatch')
        source, target = _endpoints(self.source_observation_id, self.target_observation_id, 'observation',
                                    self.relation_type in OBSERVATION_SYMMETRIC)
        object.__setattr__(self, 'source_observation_id', source)
        object.__setattr__(self, 'target_observation_id', target)
        _provenance(self.rule_id, self.reason_code)
        _time(self.created_at)

    @classmethod
    def create(cls, source: str, target: str, relation_type: str, *, rule_id: str | None = None,
               reason_code: str | None = None, created_at: str | None = None) -> 'ObservationRelation':
        return cls(observation_relation_id(source, target, relation_type), source, target, relation_type,
                   rule_id, reason_code, utc_now() if created_at is None else created_at)
