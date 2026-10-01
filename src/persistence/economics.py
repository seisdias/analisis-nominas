"""SQL adapter for immutable interpretations and atomic supporting evidence."""

import json
import sqlite3
from dataclasses import replace
from typing import Any

from src.canonical.economics import (
    AccrualInterval,
    Assessment,
    AssessmentInput,
    EconomicObservation,
    ObservationEvidence,
    Rule,
    fact_fingerprint,
    input_manifest,
)
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.persistence.evidence import EvidenceRepository, WriteOutcome

_RULE_COLUMNS = 'rule_id, family, name, version, implementation_hash, created_at'
_ASSESSMENT_COLUMNS = 'assessment_id, document_id, rule_id, input_signature, inputs_json, status, created_at'
_OBS_COLUMNS = ('observation_id, assessment_id, observation_key, magnitude, scope, nature, '
                'pay_behavior, temporal_character, payment_form, settlement_context, '
                'liquidation_period, liquidation_state, liquidation_reason, '
                'accrual_start, accrual_end, accrual_state, accrual_reason, '
                'payment_date, payment_state, payment_reason, economic_status, eligibility, confidence, '
                'value_state, coefficient, scale, currency, reason_code, created_at')


class EconomicRepository(EvidenceRepository):
    """Shares connection/transactions with documentary repositories; no rule execution.

    Observations and their nonempty support set are written in a single operation.
    Adding/changing support later is a conflict, not a silent reinterpretation.
    """

    def _insert(self, table: str, columns: str, values: tuple[Any, ...]) -> None:
        try:
            self._connection.execute(
                f'INSERT INTO {table} ({columns}) VALUES ({", ".join("?" for _ in values)})', values,
            )
        except sqlite3.IntegrityError as error:
            if error.sqlite_errorcode in (sqlite3.SQLITE_CONSTRAINT_UNIQUE, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY):
                raise ReproducibilityConflict('Conflicting interpretation identity') from error
            raise

    def register_rule(self, rule: Rule) -> WriteOutcome:
        with self.transaction():
            old = self.get_rule(rule.rule_id)
            if old is not None:
                if replace(rule, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting rule')
                return WriteOutcome.IDENTICAL
            self._insert('rules', _RULE_COLUMNS, (rule.rule_id, rule.family, rule.name,
                         rule.version, rule.implementation_hash, rule.created_at))
            return WriteOutcome.CREATED

    def get_rule(self, rule_id: str) -> Rule | None:
        row = self._connection.execute('SELECT ' + _RULE_COLUMNS + ' FROM rules WHERE rule_id=?', (rule_id,)).fetchone()
        return Rule(*row) if row is not None else None

    def _validate_inputs(self, assessment: Assessment) -> None:
        for item in assessment.inputs:
            fact = self.get_fact(item.fact_id)
            if fact is None:
                raise ValueError('Assessment references unknown input fact')
            if fact_fingerprint(fact) != item.content_hash:
                raise ReproducibilityConflict('Assessment input differs from recorded fact')
            row = self._connection.execute(
                'SELECT v.document_id FROM extractions e JOIN document_versions v '
                'ON v.version_id=e.version_id WHERE e.extraction_id=?', (fact.extraction_id,),
            ).fetchone()
            if row is None or row[0] != assessment.document_id:
                raise ValueError('Assessment input belongs to a different logical document')

    def register_assessment(self, assessment: Assessment) -> WriteOutcome:
        with self.transaction():
            self._validate_inputs(assessment)
            old = self.get_assessment(assessment.assessment_id)
            if old is not None:
                if replace(assessment, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting assessment')
                return WriteOutcome.IDENTICAL
            payload = json.dumps(input_manifest(assessment.inputs), sort_keys=True, separators=(',', ':'))
            self._insert('assessments', _ASSESSMENT_COLUMNS, (
                assessment.assessment_id, assessment.document_id, assessment.rule_id,
                assessment.input_signature, payload, assessment.status, assessment.created_at,
            ))
            return WriteOutcome.CREATED

    def get_assessment(self, assessment_id: str) -> Assessment | None:
        row = self._connection.execute('SELECT ' + _ASSESSMENT_COLUMNS + ' FROM assessments WHERE assessment_id=?', (assessment_id,)).fetchone()
        if row is None:
            return None
        identity, document, rule, signature, payload, status, stamp = row
        inputs = tuple(AssessmentInput(**item) for item in json.loads(payload))
        return Assessment(identity, document, rule, signature, inputs, status, stamp)

    def register_observation(self, observation: EconomicObservation, fact_ids: tuple[str, ...]) -> WriteOutcome:
        evidence = ObservationEvidence(observation, tuple(sorted(fact_ids)))
        with self.transaction():
            assessment = self.get_assessment(observation.assessment_id)
            if assessment is None:
                raise ValueError('Unknown assessment')
            self._validate_inputs(assessment)
            if not set(fact_ids) <= {item.fact_id for item in assessment.inputs}:
                raise ValueError('Observation support must be included in assessment inputs')
            if observation.eligibility == 'candidate' and assessment.status != 'usable':
                raise ValueError('Candidate requires a usable assessment')
            if assessment.status == 'excluded' and observation.eligibility != 'excluded':
                raise ValueError('Excluded assessment cannot yield eligible observations')
            old = self.get_observation(observation.observation_id)
            if old is not None:
                normalized = replace(evidence, observation=replace(observation, created_at=old.observation.created_at))
                if normalized != old:
                    raise ReproducibilityConflict('Conflicting observation or supporting facts')
                return WriteOutcome.IDENTICAL
            self._insert('economic_observations', _OBS_COLUMNS, _encode_observation(observation))
            for fact_id in evidence.fact_ids:
                self._insert('observation_facts', 'observation_id, fact_id', (observation.observation_id, fact_id))
            return WriteOutcome.CREATED

    def get_observation(self, observation_id: str) -> ObservationEvidence | None:
        row = self._connection.execute('SELECT ' + _OBS_COLUMNS + ' FROM economic_observations WHERE observation_id=?', (observation_id,)).fetchone()
        if row is None:
            return None
        ids = tuple(r[0] for r in self._connection.execute(
            'SELECT fact_id FROM observation_facts WHERE observation_id=? ORDER BY fact_id', (observation_id,),
        ))
        return ObservationEvidence(_decode_observation(row), ids)

    def get_observations(self, assessment_id: str) -> tuple[ObservationEvidence, ...]:
        ids = self._connection.execute(
            'SELECT observation_id FROM economic_observations WHERE assessment_id=? ORDER BY observation_key',
            (assessment_id,),
        ).fetchall()
        results = []
        for (identity,) in ids:
            item = self.get_observation(identity)
            if item is None:
                raise ValueError('Observation disappeared during retrieval')
            results.append(item)
        return tuple(results)


def _encode_observation(o: EconomicObservation) -> tuple[Any, ...]:
    number = o.value.value
    assert number is None or isinstance(number, ExactDecimal)
    return (o.observation_id, o.assessment_id, o.observation_key, o.magnitude, o.scope, o.nature,
            o.pay_behavior, o.temporal_character, o.payment_form, o.settlement_context,
            o.liquidation_period.value, o.liquidation_period.state.value, o.liquidation_period.reason_code,
            o.accrual.start, o.accrual.end, o.accrual.state.value, o.accrual.reason_code,
            o.payment_date.value, o.payment_date.state.value, o.payment_date.reason_code,
            o.economic_status, o.eligibility, o.confidence, o.value.state.value,
            number.coefficient if number is not None else None, number.scale if number is not None else None,
            o.value.currency.code if o.value.currency is not None else None, o.value.reason_code, o.created_at)


def _decode_observation(row: tuple[Any, ...]) -> EconomicObservation:
    (identity, assessment, key, magnitude, scope, nature, pay, temporal, payment, context,
     month, month_state, month_reason, start, end, accrual_state, accrual_reason,
     pay_date, date_state, date_reason, status, eligibility, confidence, value_state,
     coefficient, scale, currency, reason, stamp) = row
    return EconomicObservation(
        observation_id=identity, assessment_id=assessment, observation_key=key, magnitude=magnitude,
        scope=scope, nature=nature, pay_behavior=pay, temporal_character=temporal, payment_form=payment,
        settlement_context=context, economic_status=status, eligibility=eligibility, confidence=confidence,
        value=CanonicalValue(state=ValueState(value_state), value=ExactDecimal(coefficient, scale) if coefficient is not None else None,
                             currency=CurrencyCode(currency) if currency is not None else None, reason_code=reason),
        liquidation_period=CanonicalValue(state=ValueState(month_state), value=month, reason_code=month_reason),
        accrual=AccrualInterval(ValueState(accrual_state), start, end, accrual_reason),
        payment_date=CanonicalValue(state=ValueState(date_state), value=pay_date, reason_code=date_reason),
        created_at=stamp,
    )
