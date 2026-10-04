"""Atomic revision-checked cache publication; no calculation or economic rules."""

import sqlite3
from dataclasses import replace

from src.canonical.derived import CalculationInputs, DerivedInput, DerivedResult, _inputs
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.persistence.evidence import WriteOutcome
from src.persistence.relations import RelationRepository
from src.persistence.state import CanonicalStateReader

_COLUMNS = ('result_id,rule_id,parameters_json,dataset_revision,output_key,result_type,'
            'value_state,coefficient,scale,currency,reason_code,status,created_at')


class DatasetRevisionConflict(ReproducibilityConflict):
    """Source state changed; the computed result cannot be published."""


class DerivedRepository(RelationRepository):
    def dataset_revision(self) -> str:
        return CanonicalStateReader(self._connection).read().fingerprint

    def capture_inputs(self, inputs: tuple[DerivedInput, ...]) -> CalculationInputs:
        with self.transaction():
            ordered = _inputs(inputs)
            values = []
            for item in ordered:
                if item.kind == 'observation':
                    observation = self.get_observation(item.target_id)
                    if observation is None:
                        raise ValueError('Unknown observation input')
                    values.append(observation.observation.value)
                else:
                    fact = self.get_fact(item.target_id)
                    if fact is None:
                        raise ValueError('Unknown documentary input')
                    values.append(fact.value)
            return CalculationInputs(self.dataset_revision(), ordered, tuple(values))

    def publish(self, result: DerivedResult) -> WriteOutcome:
        if result.status != 'ready':
            raise ValueError('Invalid result cannot be published')
        return self._store(result)

    def record_invalid(self, result: DerivedResult) -> WriteOutcome:
        if result.status != 'invalid':
            raise ValueError('Explicit invalid result required')
        return self._store(result)

    def _store(self, result: DerivedResult) -> WriteOutcome:
        try:
            with self.transaction():
                if self.get_rule(result.rule_id) is None:
                    raise ValueError('Register the responsible rule before capturing the revision')
                captured = self.capture_inputs(result.inputs)
                if captured.dataset_revision != result.dataset_revision:
                    raise DatasetRevisionConflict('Dataset changed during calculation; publication refused')
                old = self.get_result(result.result_id)
                if old is not None:
                    if replace(result, created_at=old.created_at) != old:
                        raise ReproducibilityConflict('Same calculation identity produced incompatible content')
                    return WriteOutcome.IDENTICAL
                number = result.value.value
                assert number is None or isinstance(number, ExactDecimal)
                self._insert('derived_results', _COLUMNS, (
                    result.result_id, result.rule_id, result.parameters_json, result.dataset_revision,
                    result.output_key, result.result_type, result.value.state.value,
                    None if number is None else number.coefficient, None if number is None else number.scale,
                    None if result.value.currency is None else result.value.currency.code,
                    result.value.reason_code, result.status, result.created_at))
                for item in result.inputs:
                    self._insert('derived_inputs', 'result_id,input_id,observation_id,fact_id', (
                        result.result_id, item.target_id, item.target_id if item.kind == 'observation' else None,
                        item.target_id if item.kind == 'fact' else None))
                return WriteOutcome.CREATED
        except sqlite3.OperationalError as error:
            # A concurrent commit cannot upgrade a stale SQLite read snapshot to
            # a write. Fail closed on BUSY/LOCKED, never retry without revalidation.
            if getattr(error, 'sqlite_errorcode', 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise DatasetRevisionConflict('Publication could not retain the checked source snapshot') from error
            raise

    def get_result(self, result_id: str) -> DerivedResult | None:
        with self.transaction():
            row = self._connection.execute('SELECT '+_COLUMNS+' FROM derived_results WHERE result_id=?', (result_id,)).fetchone()
            if row is None:
                return None
            links = self._connection.execute('SELECT observation_id,fact_id FROM derived_inputs WHERE result_id=?', (result_id,))
            inputs = _inputs(tuple(DerivedInput('observation' if obs is not None else 'fact', obs if obs is not None else fact)
                                   for obs, fact in links))
            (identity, rule, params, revision, key, kind, state, coefficient, scale, currency, reason, status, stamp) = row
            value = CanonicalValue(state=ValueState(state), value=None if coefficient is None else ExactDecimal(coefficient, scale),
                                   currency=None if currency is None else CurrencyCode(currency), reason_code=reason)
            return DerivedResult(identity, rule, params, revision, inputs, key, kind, value, status, stamp)

    def freshness(self, result_id: str) -> str:
        with self.transaction():
            result = self.get_result(result_id)
            if result is None:
                raise KeyError('Unknown derived result')
            if result.status == 'invalid':
                return 'invalid'
            return 'current' if result.dataset_revision == self.dataset_revision() else 'stale'
