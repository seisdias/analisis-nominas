"""Portable append-only acknowledgements; no economic effects or resolutions.

Version 1 supports only documentary-fact acknowledgement. It has no winner or
mutable active state, so revocation/supersession is deliberately not introduced.
A future effectful decision type needs its own precondition and lifecycle contract.
"""

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from src.canonical.evidence import _id, _sha, _time, utc_now
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.serialization import canonical_bytes, deterministic_id


def _reject_number(value: str) -> None:
    raise ValueError('Floating/nonfinite numbers are not portable decision values')


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _loads(data: str | bytes) -> Any:
    return json.loads(data, parse_float=_reject_number, parse_constant=_reject_number,
                      object_pairs_hook=_pairs)


def _json(value: object) -> str:
    canonical_bytes(value)  # Certified closed value vocabulary; no floats/coercions.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True, slots=True)
class ManualDecision:
    decision_id: str
    decision_type: str
    target_type: str
    target_id: str
    payload_json: str
    precondition_hash: str
    created_at: str
    created_by: str

    def __post_init__(self) -> None:
        payload = _loads(self.payload_json)
        semantic = {'decision_type': self.decision_type, 'target_type': self.target_type,
                    'target_id': str(self.target_id), 'payload': payload,
                    'precondition_hash': self.precondition_hash, 'created_by': self.created_by}
        if self.decision_id != deterministic_id('manual_decision', semantic):
            raise ReproducibilityConflict('Decision identity differs from semantic content')
        if self.decision_type != 'acknowledge_documentary_fact' or self.target_type != 'documentary_fact':
            raise ValueError('Unsupported manual decision/target type')
        if payload != {'acknowledged': True} or type(payload.get('acknowledged')) is not bool:
            raise ValueError('Only explicit acknowledgement is supported')
        if self.payload_json != _json(payload):
            raise ValueError('Canonical decision payload required')
        _id(self.target_id, 'fact')
        _sha(self.precondition_hash)
        _time(self.created_at)
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}', self.created_by):
            raise ValueError('Use a local actor alias, not PII or a path')

    @classmethod
    def create(cls, target_id: str, precondition_hash: str, *, created_by: str,
               created_at: str | None = None) -> 'ManualDecision':
        semantic = {'decision_type': 'acknowledge_documentary_fact', 'target_type': 'documentary_fact',
                    'target_id': str(target_id), 'payload': {'acknowledged': True},
                    'precondition_hash': precondition_hash, 'created_by': created_by}
        return cls(deterministic_id('manual_decision', semantic), 'acknowledge_documentary_fact',
                   'documentary_fact', target_id, _json({'acknowledged': True}), precondition_hash,
                   utc_now() if created_at is None else created_at, created_by)


def encode_decisions(decisions: tuple[ManualDecision, ...]) -> bytes:
    """Readable JSON v1; identity hashes use the certified canonical serializer.

    Sort by ID; exact duplicate records collapse. Conflicting audit records in a
    portable bundle are rejected rather than choosing a timestamp by input order.
    """
    unique: dict[str, ManualDecision] = {}
    for item in decisions:
        previous = unique.get(item.decision_id)
        if previous is not None and previous != item:
            raise ReproducibilityConflict('Conflicting duplicate portable decision')
        unique[item.decision_id] = item
    return _json({'contract': 'manual-decisions', 'version': 1,
                  'decisions': [asdict(unique[key]) for key in sorted(unique)]}).encode('utf-8')


def decode_decisions(data: bytes) -> tuple[ManualDecision, ...]:
    envelope = _loads(data)
    if (type(envelope) is not dict or set(envelope) != {'contract', 'version', 'decisions'}
            or envelope['contract'] != 'manual-decisions' or type(envelope['version']) is not int
            or envelope['version'] != 1 or type(envelope['decisions']) is not list):
        raise ValueError('Unsupported portable decisions contract')
    result = []
    fields = set(ManualDecision.__dataclass_fields__)
    for row in envelope['decisions']:
        if type(row) is not dict or set(row) != fields or any(type(v) is not str for v in row.values()):
            raise ValueError('Invalid portable decision record')
        result.append(ManualDecision(**row))
    encode_decisions(tuple(result))  # Validate and reject conflicting duplicate audit records.
    # Deduplicate without using insertion order or accepting conflicting records.
    ids = sorted({item.decision_id for item in result})
    by_id = {item.decision_id: item for item in result}
    return tuple(by_id[key] for key in ids)
