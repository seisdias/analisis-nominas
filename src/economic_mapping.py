"""Direct documentary totals only: no aggregation, period inference or version selection."""

from importlib.resources import files

from src.canonical.economics import (
    Assessment,
    EconomicObservation,
    Interpretation,
    ObservationEvidence,
    Rule,
    observation_id,
)
from src.canonical.evidence import utc_now
from src.canonical.facts import DocumentaryFact
from src.canonical.serialization import sha256_bytes
from src.canonical.values import ExactDecimal, ValueState


def direct_totals_rule(*, created_at: str | None = None) -> Rule:
    implementation = files('src').joinpath('economic_mapping.py').read_bytes()
    return Rule.define('documentary_mapping', 'direct_totals', '1', sha256_bytes(implementation),
                       created_at=created_at)


def evaluate_direct_totals(document_id: str, facts: tuple[DocumentaryFact, ...], *,
                           created_at: str | None = None) -> Interpretation:
    stamp = utc_now() if created_at is None else created_at
    rule = direct_totals_rule(created_at=stamp)
    targets = {'nomina.total_devengado': 'documentary_gross',
               'nomina.liquido_percibir': 'documentary_net'}
    if len({f.fact_id for f in facts}) != len(facts):
        raise ValueError('Repeated input identity; no automatic deduplication')
    by_key = {f.fact_key: f for f in facts}
    if len({f.extraction_id for f in facts}) > 1:
        status = 'ambiguous'
    elif not targets.keys() <= by_key.keys():
        status = 'incomplete'
    elif any(by_key[key].value.state != ValueState.PRESENT for key in targets):
        status = 'pending'
    elif any(type(by_key[key].value.value) is not ExactDecimal for key in targets):
        status = 'incomplete'
    else:
        status = 'usable'
    assessment = Assessment.from_facts(document_id, rule.rule_id, facts, status, created_at=stamp)
    observations = []
    if status == 'usable':
        for key, magnitude in sorted(targets.items()):
            fact = by_key[key]
            observation = EconomicObservation(
                observation_id=observation_id(assessment.assessment_id, key),
                assessment_id=assessment.assessment_id, observation_key=key, magnitude=magnitude,
                value=fact.value, economic_status='usable', eligibility='evidence_only',
                confidence='mapped', created_at=stamp,
            )
            observations.append(ObservationEvidence(observation, (fact.fact_id,)))
    return Interpretation(rule, assessment, tuple(observations))
