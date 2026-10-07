"""Pure readiness checks; no persistence, relation resolution or authorization."""
from dataclasses import FrozenInstanceError, replace

import pytest

from src.canonical.certification import (
    CertificationRequirements,
    DocumentarySupport,
    EconomicEligibility,
)
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import Assessment
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.readiness import (
    CandidacyContext,
    CandidacyReadiness,
    CandidacyReason,
    evaluate_candidacy_readiness,
)
from src.canonical.serialization import deterministic_id
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.economic_mapping import evaluate_direct_totals


@pytest.fixture
def sample():
    corpus = deterministic_id('corpus', 'readiness')
    doc = LogicalDocument(document_id(corpus, 'unit'), corpus, None, 'synthetic', 'unit')
    file = deterministic_id('file', 'readiness')
    ver = DocumentVersion(version_id(doc.document_id, file, 'whole'), doc.document_id, file, 'whole')
    ext = Extraction(extraction_id(ver.version_id, 'synthetic', '1', 'a'*64),
                     ver.version_id, 'synthetic', '1', 'a'*64, 'b'*64)
    facts = tuple(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(key,
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0))))
        for key in ('nomina.total_devengado', 'nomina.liquido_percibir'))
    result = evaluate_direct_totals(doc.document_id, facts)
    return result.observations, DocumentarySupport(doc, ver, ext, result.rule, result.assessment, facts)


COMPLETE = CandidacyContext(relational_snapshot_complete=True)


@pytest.mark.parametrize('index', [0, 1])
def test_evidence_only_and_explicit_zero_ready(sample, index):
    items, support = sample
    result = evaluate_candidacy_readiness(items[index], support, context=COMPLETE)
    assert result.readiness is CandidacyReadiness.READY
    assert result.persisted_eligibility is EconomicEligibility.EVIDENCE_ONLY
    assert result.reasons == ()
    assert result.certification.value.value == ExactDecimal(0, 0)
    assert items[index].observation.eligibility == 'evidence_only'


@pytest.mark.parametrize('eligibility', ['candidate', 'evidence_only'])
def test_context_requirements_are_equal_for_existing_eligibilities(sample, eligibility):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, eligibility=eligibility))
    result = evaluate_candidacy_readiness(item, support, context=COMPLETE,
                                          requirements=CertificationRequirements(currency=True))
    assert result.readiness is CandidacyReadiness.BLOCKED
    assert CandidacyReason.CONTEXT_REQUIREMENTS_UNSATISFIED in result.reasons
    assert result.certification.context_reasons[0].value == 'context.currency_unknown'


def test_excluded_blocks_even_certified_value(sample):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, eligibility='excluded'))
    result = evaluate_candidacy_readiness(item, support, context=COMPLETE)
    assert result.readiness is CandidacyReadiness.BLOCKED
    assert result.reasons == (CandidacyReason.ELIGIBILITY_EXCLUDED,)


@pytest.mark.parametrize('state', [s for s in ValueState if s != ValueState.PRESENT])
def test_uncertainty_not_ready(sample, state):
    items, support = sample
    value = CanonicalValue(state=state, reason_code='synthetic.uncertain')
    item = replace(items[0], observation=replace(items[0].observation, value=value,
                                               economic_status='pending'))
    result = evaluate_candidacy_readiness(item, support, context=COMPLETE)
    assert result.readiness is CandidacyReadiness.BLOCKED
    assert CandidacyReason.CERTIFICATION_BLOCKED in result.reasons


def test_unsupported_magnitude(sample):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, magnitude='unsupported'))
    result = evaluate_candidacy_readiness(item, support, context=COMPLETE)
    assert result.readiness is CandidacyReadiness.BLOCKED
    assert any(r.value == 'magnitude.unsupported' for r in result.certification.value_reasons)


def test_default_context_cannot_claim_completeness(sample):
    items, support = sample
    result = evaluate_candidacy_readiness(items[0], support)
    assert result.readiness is CandidacyReadiness.NOT_EVALUATED
    assert result.reasons == (CandidacyReason.RELATIONAL_SNAPSHOT_INCOMPLETE,)


def test_incomplete_required_context_takes_precedence_without_hiding_blockers(sample):
    items, support = sample
    item = replace(items[0], observation=replace(items[0].observation, eligibility='excluded'))
    result = evaluate_candidacy_readiness(item, support)
    assert result.readiness is CandidacyReadiness.NOT_EVALUATED
    assert CandidacyReason.ELIGIBILITY_EXCLUDED in result.reasons
    assert CandidacyReason.RELATIONAL_SNAPSHOT_INCOMPLETE in result.reasons


def test_context_not_required_is_explicit(sample):
    items, support = sample
    context = CandidacyContext(relational_context_required=False)
    assert evaluate_candidacy_readiness(items[0], support, context=context).readiness is CandidacyReadiness.READY


def test_recertifies_inputs_without_mutation_or_order_dependence(sample, monkeypatch):
    import src.canonical.readiness as module
    items, support = sample
    before = (items, support)
    original = module.certify_observation
    calls = []
    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'certify_observation', spy)
    a = evaluate_candidacy_readiness(items[0], support, context=COMPLETE)
    b = evaluate_candidacy_readiness(items[0], replace(support, facts=tuple(reversed(support.facts))), context=COMPLETE)
    assert a == b and len(calls) == 2
    assert (items, support) == before
    bad = evaluate_candidacy_readiness(items[0], replace(support, facts=()), context=COMPLETE)
    assert bad.readiness is CandidacyReadiness.BLOCKED
    with pytest.raises(FrozenInstanceError):
        setattr(a, 'readiness', CandidacyReadiness.BLOCKED)
    assert not hasattr(a, 'additive')
    assert not hasattr(a, 'created_at')


@pytest.mark.parametrize('status', ['pending', 'ambiguous', 'excluded', 'incomplete'])
def test_nonusable_assessments_do_not_pass(sample, status):
    items, support = sample
    assessment = Assessment.from_facts(support.document.document_id, support.rule.rule_id, support.facts, status)
    result = evaluate_candidacy_readiness(items[0], replace(support, assessment=assessment), context=COMPLETE)
    assert result.readiness is CandidacyReadiness.BLOCKED


@pytest.mark.parametrize('value', [None, 0, 'yes'])
def test_completeness_requires_explicit_boolean(value):
    with pytest.raises(TypeError):
        CandidacyContext(relational_snapshot_complete=value)
