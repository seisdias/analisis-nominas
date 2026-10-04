"""Reconstructible exact cache contracts; no economic formulas or rule engine."""

import json
from dataclasses import dataclass, field

from src.canonical.evidence import _decode_plan, _id, _sha, _text, _time, utc_now
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.serialization import canonical_bytes, deterministic_id
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState


def _parameters(payload: str) -> None:
    envelope = json.loads(payload)
    if (type(envelope) is not dict or set(envelope) != {'contract', 'version', 'value'}
            or envelope['contract'] != 'canonical' or type(envelope['version']) is not int
            or envelope['version'] != 1):
        raise ValueError('Canonical parameter envelope required')
    value = _decode_plan(envelope['value'])
    if type(value) is not dict or canonical_bytes(value).decode('utf-8') != payload:
        raise ValueError('Canonical primitive parameter map required')


@dataclass(frozen=True, slots=True)
class DerivedInput:
    kind: str
    target_id: str

    def __post_init__(self) -> None:
        if self.kind not in ('observation', 'fact'):
            raise ValueError('Unsupported derived input kind')
        _id(self.target_id, self.kind)


def _inputs(inputs: tuple[DerivedInput, ...]) -> tuple[DerivedInput, ...]:
    if type(inputs) is not tuple or not inputs or any(type(i) is not DerivedInput for i in inputs):
        raise ValueError('Nonempty immutable typed inputs required')
    if len(set(inputs)) != len(inputs):
        raise ValueError('Duplicate derived input')
    return tuple(sorted(inputs, key=lambda i: (i.kind, i.target_id)))


def derived_id(rule_id: str, parameters_json: str, dataset_revision: str,
               inputs: tuple[DerivedInput, ...], output_key: str) -> str:
    return deterministic_id('derived', {'rule': str(rule_id), 'parameters': parameters_json,
        'revision': dataset_revision, 'inputs': [{'kind': i.kind, 'id': str(i.target_id)} for i in _inputs(inputs)],
        'output_key': output_key})


@dataclass(frozen=True, slots=True)
class DerivedResult:
    result_id: str
    rule_id: str
    parameters_json: str
    dataset_revision: str
    inputs: tuple[DerivedInput, ...]
    output_key: str
    result_type: str
    value: CanonicalValue
    status: str = 'ready'
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _id(self.rule_id, 'rule')
        _sha(self.dataset_revision)
        _parameters(self.parameters_json)
        _text(self.output_key)
        _text(self.result_type)
        _time(self.created_at)
        if self.inputs != _inputs(self.inputs):
            raise ValueError('Inputs must be in canonical order')
        if self.result_id != derived_id(self.rule_id, self.parameters_json, self.dataset_revision, self.inputs, self.output_key):
            raise ReproducibilityConflict('Derived identity differs from calculation inputs')
        if type(self.value) is not CanonicalValue or (self.value.value is not None and type(self.value.value) is not ExactDecimal):
            raise ValueError('Derived value must be an exact decimal or uncertainty')
        if self.status not in ('ready', 'invalid'):
            raise ValueError('Invalid result state')
        if self.status == 'ready' and self.value.state != ValueState.PRESENT:
            raise ValueError('Ready result requires a present exact value')

    @classmethod
    def create(cls, rule_id: str, parameters: object, dataset_revision: str,
               inputs: tuple[DerivedInput, ...], output_key: str, result_type: str,
               value: CanonicalValue, *, status: str = 'ready', created_at: str | None = None) -> 'DerivedResult':
        payload = canonical_bytes(parameters).decode('utf-8')
        ordered = _inputs(inputs)
        return cls(derived_id(rule_id, payload, dataset_revision, ordered, output_key), rule_id,
                   payload, dataset_revision, ordered, output_key, result_type, value, status,
                   utc_now() if created_at is None else created_at)


@dataclass(frozen=True, slots=True)
class CalculationInputs:
    dataset_revision: str
    inputs: tuple[DerivedInput, ...]
    values: tuple[CanonicalValue, ...]
