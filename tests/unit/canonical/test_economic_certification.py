"""Certification is local evidence validation, never economic selection."""
from dataclasses import replace

import pytest

from src.canonical.certification import (
    CertificationReason as Reason,
)
from src.canonical.certification import (
    CertificationRequirements,
    DocumentarySupport,
    certify_observation,
)
from src.canonical.certification import (
    CertificationStatus as Status,
)
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import AccrualInterval, Assessment, Rule
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.serialization import deterministic_id
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.economic_mapping import evaluate_direct_totals


@pytest.fixture
def sample():
    corpus = deterministic_id('corpus', 'synthetic')
    doc = LogicalDocument(document_id(corpus, 'origin'), corpus, None, 'synthetic', 'origin')
    file = deterministic_id('file', 'synthetic')
    ver = DocumentVersion(version_id(doc.document_id, file, 'whole'), doc.document_id, file, 'whole')
    ext = Extraction(extraction_id(ver.version_id, 'synthetic', '1', 'a'*64),
                     ver.version_id, 'synthetic', '1', 'a'*64, 'b'*64)
    facts = tuple(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(key,
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0))))
        for key in ('nomina.total_devengado', 'nomina.liquido_percibir'))
    result = evaluate_direct_totals(doc.document_id, facts)
    support = DocumentarySupport(doc, ver, ext, result.rule, result.assessment, facts)
    return result.observations, support


@pytest.mark.parametrize('index', [0, 1])
def test_direct_totals_and_explicit_zero_certified_without_promotion(sample, index):
    items, support = sample
    item = items[index]
    result = certify_observation(item, support)
    assert result.value_status == Status.CERTIFIED
    assert result.context_reasons == ()
    assert result.eligibility == 'evidence_only'
    assert result.value == CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0))
    assert result == certify_observation(item, support)
    assert not hasattr(result, 'additive')


@pytest.mark.parametrize('state', [s for s in ValueState if s != ValueState.PRESENT])
def test_uncertain_values_never_certified(sample, state):
    items, support = sample
    value = CanonicalValue(state=state, reason_code='synthetic.uncertain')
    item = replace(items[0], observation=replace(items[0].observation, value=value,
                                               economic_status='pending'))
    result = certify_observation(item, support)
    assert result.value_status == Status.BLOCKED
    assert Reason.VALUE_UNUSABLE in result.value_reasons


def test_unsupported_magnitude(sample):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, magnitude='annual_gross'))
    assert Reason.UNSUPPORTED_MAGNITUDE in certify_observation(item, support).value_reasons


@pytest.mark.parametrize('requirement,reason', [
    ('currency', Reason.CURRENCY_UNKNOWN), ('employer', Reason.EMPLOYER_UNKNOWN),
    ('liquidation_period', Reason.LIQUIDATION_UNKNOWN),
    ('accrual_interval', Reason.ACCRUAL_UNKNOWN), ('payment_date', Reason.PAYMENT_UNKNOWN),
])
def test_context_blocks_use_not_documentary_value(sample, requirement, reason):
    items, support = sample
    item = items[0]
    before = (item, support)
    result = certify_observation(item, support, CertificationRequirements(**{requirement: True}))
    assert result.value_status == Status.CERTIFIED
    assert result.context_reasons == (reason,)
    assert not result.context_satisfied
    assert (item, support) == before


def test_explicit_temporal_context_satisfies_only_requested_axes(sample):
    items, support = sample
    obs = replace(items[0].observation,
        liquidation_period=CanonicalValue(state=ValueState.PRESENT, value='2026-01'),
        accrual=AccrualInterval(ValueState.PRESENT, '2025-12-03', '2025-12-07'),
        payment_date=CanonicalValue(state=ValueState.PRESENT, value='2026-02-02'))
    result = certify_observation(replace(items[0], observation=obs), support,
        CertificationRequirements(liquidation_period=True, accrual_interval=True, payment_date=True))
    assert result.context_satisfied


@pytest.mark.parametrize('mutation', ['missing', 'changed', 'wrong_version', 'wrong_rule'])
def test_insufficient_or_inconsistent_provenance(sample, mutation):
    items, support = sample
    if mutation == 'missing':
        support = replace(support, facts=())
    elif mutation == 'changed':
        fact = replace(support.facts[0], value=CanonicalValue(state=ValueState.PRESENT,
                                                            value=ExactDecimal(99, 0)))
        support = replace(support, facts=(fact, *support.facts[1:]))
    elif mutation == 'wrong_version':
        ver = support.version
        support = replace(support, version=replace(ver, segment_key='other',
            version_id=version_id(ver.document_id, ver.file_id, 'other')))
    else:
        support = replace(support, rule=Rule.define(
            'other', 'other', '1', 'c'*64))
    assert Reason.PROVENANCE_INSUFFICIENT in certify_observation(items[0], support).value_reasons


def test_value_must_match_support_no_reconstruction(sample):
    items, support = sample
    obs = replace(items[0].observation, value=CanonicalValue(state=ValueState.PRESENT,
                                                            value=ExactDecimal(10, 0)))
    assert Reason.SUPPORT_MISMATCH in certify_observation(replace(items[0], observation=obs), support).value_reasons


@pytest.mark.parametrize('eligibility', ['candidate', 'evidence_only', 'excluded'])
def test_certification_preserves_eligibility_and_never_selects(sample, eligibility):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, eligibility=eligibility))
    result = certify_observation(item, support)
    assert result.value_status == Status.CERTIFIED
    assert result.eligibility == eligibility
    assert not hasattr(result, 'additive')
    assert certify_observation(items[1], support).value_status == Status.CERTIFIED


def test_fact_enumeration_order_irrelevant(sample):
    items, support = sample
    assert certify_observation(items[0], support) == certify_observation(
        items[0], replace(support, facts=tuple(reversed(support.facts))))


@pytest.mark.parametrize('amount', ['201.53', '-201.53'])
def test_exact_nonzero_currency_and_employer_context(sample, amount):
    _, support = sample
    value = CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal.from_text(amount),
                           currency=CurrencyCode('EUR'))
    facts = tuple(replace(f, value=value) for f in support.facts)
    interpretation = evaluate_direct_totals(support.document.document_id, facts)
    support = replace(support, facts=facts, assessment=interpretation.assessment,
        document=replace(support.document, employer_id=deterministic_id('employer', 'explicit')))
    result = certify_observation(interpretation.observations[0], support,
                                CertificationRequirements(currency=True, employer=True))
    assert result.value_status == Status.CERTIFIED
    assert result.context_satisfied
    assert result.value == value


@pytest.mark.parametrize('status', ['pending', 'ambiguous', 'excluded', 'incomplete'])
def test_nonusable_assessment_is_not_promoted(sample, status):
    items, support = sample
    assessment = Assessment.from_facts(support.document.document_id, support.rule.rule_id,
                                      support.facts, status)
    result = certify_observation(items[0], replace(support, assessment=assessment))
    assert result.value_status == Status.BLOCKED
    assert Reason.ASSESSMENT_UNUSABLE in result.value_reasons


def test_extra_support_does_not_authorize_sum(sample):
    items, support = sample
    item = replace(items[0], fact_ids=tuple(sorted(f.fact_id for f in support.facts)))
    assert Reason.SUPPORT_MISMATCH in certify_observation(item, support).value_reasons


@pytest.mark.parametrize('field,value', [('scope', 'component'), ('confidence', 'inferred'),
                                       ('confidence', 'reconstructed')])
def test_only_direct_total_evidence_is_certified(sample, field, value):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, **{field: value}))
    assert Reason.SUPPORT_MISMATCH in certify_observation(item, support).value_reasons
