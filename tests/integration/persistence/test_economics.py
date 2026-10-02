"""Synthetic interpretation infrastructure; no corpus, totals aggregation or selection."""

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest

from src.canonical import (
    CanonicalValue,
    CurrencyCode,
    ExactDecimal,
    ReproducibilityConflict,
    ValueState,
)
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import (
    AccrualInterval,
    Assessment,
    Rule,
    observation_id,
)
from src.canonical.evidence import (
    Corpus,
    Person,
    SourceFile,
    corpus_id,
    person_id,
    source_file_id,
)
from src.canonical.facts import DocumentaryFact, FactDraft
from src.economic_mapping import direct_totals_rule, evaluate_direct_totals
from src.persistence import (
    load_migrations as packaged_migrations,
)
from src.persistence import (
    open_database as packaged_open_database,
)
from src.persistence import (
    verify_schema as packaged_verify_schema,
)
from src.persistence.economics import EconomicRepository
from src.persistence.evidence import WriteOutcome


# Preserve v5-specific assertions; test_relations.py exercises the packaged v6.
def load_migrations():
    return packaged_migrations()[:5]


def open_database(path: str | Path, *, mode: Literal['create', 'migrate', 'verify'] = 'verify',
                  **kwargs: Any):
    kwargs.setdefault('migrations', load_migrations())
    return packaged_open_database(path, mode=mode, **kwargs)


def verify_schema(connection):
    return packaged_verify_schema(connection, load_migrations())


STAMP = '2026-01-01T00:00:00Z'


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = EconomicRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'v1')
        file = SourceFile(source_file_id('a'*64), 'a'*64, 1, 'application/pdf')
        doc = LogicalDocument(document_id(corpus.corpus_id, 'unit'), corpus.corpus_id, None, 'unknown', 'unit')
        version = DocumentVersion(version_id(doc.document_id, file.file_id, 'whole'), doc.document_id, file.file_id, 'whole')
        extraction = Extraction(extraction_id(version.version_id, 'synthetic', '1', 'b'*64), version.version_id, 'synthetic', '1', 'b'*64, 'c'*64)
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(file)
        repo.register_document(doc)
        repo.register_version(version)
        repo.register_extraction(extraction)
        facts = tuple(DocumentaryFact.from_draft(extraction.extraction_id,
                      FactDraft(key, CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(amount, 2))),
                      created_at=STAMP) for key, amount in [('nomina.total_devengado', 20153), ('nomina.liquido_percibir', -153)])
        for fact in facts:
            repo.register_fact(fact)
        yield repo, db.connection, doc, version, extraction, facts


def register_evaluation(store):
    repo, _, doc, _, _, facts = store
    result = evaluate_direct_totals(doc.document_id, facts, created_at=STAMP)
    repo.register_rule(result.rule)
    repo.register_assessment(result.assessment)
    for item in result.observations:
        repo.register_observation(item.observation, item.fact_ids)
    return result


def test_rule_identity_changes_with_version_and_implementation(store):
    repo, _, _, _, _, _ = store
    rule = Rule.define('synthetic', 'test', '1', 'a'*64, created_at=STAMP)
    assert rule.rule_id == Rule.define('synthetic', 'test', '1', 'a'*64).rule_id
    assert rule.rule_id != Rule.define('synthetic', 'test', '2', 'a'*64).rule_id
    assert rule.rule_id != Rule.define('synthetic', 'test', '1', 'b'*64).rule_id
    assert repo.register_rule(rule) == WriteOutcome.CREATED
    assert repo.register_rule(replace(rule, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_rule(rule.rule_id) == rule


@pytest.mark.parametrize('status', ['usable', 'pending', 'ambiguous', 'excluded', 'incomplete'])
def test_assessment_reproducible_manifest_and_states(store, status):
    repo, _, doc, _, _, facts = store
    rule = direct_totals_rule(created_at=STAMP)
    repo.register_rule(rule)
    assessment = Assessment.from_facts(doc.document_id, rule.rule_id, facts, status, created_at=STAMP)
    reordered = Assessment.from_facts(doc.document_id, rule.rule_id, tuple(reversed(facts)), status, created_at=STAMP)
    assert assessment == reordered
    assert repo.register_assessment(assessment) == WriteOutcome.CREATED
    assert repo.register_assessment(reordered) == WriteOutcome.IDENTICAL
    assert repo.get_assessment(assessment.assessment_id) == assessment
    with pytest.raises(ReproducibilityConflict):
        repo.register_assessment(replace(assessment, status='pending' if status != 'pending' else 'excluded'))


def test_direct_mapping_no_economic_arithmetic_and_preserved_provenance(store):
    repo, _, doc, _, _, facts = store
    result = register_evaluation(store)
    assert result.assessment.status == 'usable'
    assert len(result.observations) == 2
    expected = {'documentary_gross': facts[0], 'documentary_net': facts[1]}
    for item in result.observations:
        observation = item.observation
        fact = expected[observation.magnitude]
        assert observation.value == fact.value
        assert item.fact_ids == (fact.fact_id,)
        assert observation.eligibility == 'evidence_only'
        assert observation.confidence == 'mapped'
        assert observation.liquidation_period.state == ValueState.UNKNOWN
        assert observation.accrual.state == ValueState.UNKNOWN
        assert observation.payment_date.state == ValueState.UNKNOWN
        assert repo.get_observation(observation.observation_id) == item
        assert repo.register_observation(observation, item.fact_ids) == WriteOutcome.IDENTICAL
        assert repo.get_fact(fact.fact_id) == fact
    assert repo.get_observations(result.assessment.assessment_id) == result.observations
    assert result == evaluate_direct_totals(doc.document_id, facts, created_at=STAMP)


@pytest.mark.parametrize('state', [ValueState.UNKNOWN, ValueState.UNRELIABLE, ValueState.NOT_EXTRACTED])
def test_uncertain_fact_not_promoted(store, state):
    _, _, doc, _, _, facts = store
    value = CanonicalValue(state=state, value=ExactDecimal(0, 0) if state == ValueState.UNRELIABLE else None,
                           reason_code='legacy.zero_origin_unknown' if state == ValueState.UNRELIABLE else None)
    changed = (replace(facts[0], value=value), facts[1])
    result = evaluate_direct_totals(doc.document_id, changed, created_at=STAMP)
    assert result.assessment.status in ('pending', 'incomplete')
    assert result.observations == ()


def test_missing_fields_and_legacy_liquido_alias_not_inferred(store):
    _, _, doc, _, extraction, facts = store
    alias = DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('nomina.liquido', facts[1].value))
    result = evaluate_direct_totals(doc.document_id, (facts[0], alias))
    assert result.assessment.status == 'incomplete'
    assert not result.observations


def test_no_version_selection_or_document_deduplication(store):
    repo, _, doc, version, _, facts = store
    other_version = replace(version, segment_key='other', version_id=version_id(doc.document_id, version.file_id, 'other'))
    repo.register_version(other_version)
    other_extraction = Extraction(extraction_id(other_version.version_id, 'synthetic', '1', 'b'*64), other_version.version_id, 'synthetic', '1', 'b'*64, 'c'*64)
    repo.register_extraction(other_extraction)
    others = tuple(DocumentaryFact.from_draft(other_extraction.extraction_id, FactDraft(f.fact_key, f.value)) for f in facts)
    result = evaluate_direct_totals(doc.document_id, (*facts, *others))
    assert result.assessment.status == 'ambiguous'
    assert not result.observations
    with pytest.raises(ValueError):
        evaluate_direct_totals(doc.document_id, (*facts, facts[0]))


def test_dimensions_temporality_multiple_facts_roundtrip(store):
    repo, _, _, _, _, facts = store
    result = register_evaluation(store)
    original = result.observations[0].observation
    obs = replace(original, observation_id=observation_id(result.assessment.assessment_id, 'synthetic'),
                  observation_key='synthetic', scope='component', nature='synthetic', pay_behavior='variable',
                  temporal_character='arrears', payment_form='mixed', settlement_context='synthetic',
                  liquidation_period=CanonicalValue(state=ValueState.PRESENT, value='2026-01'),
                  accrual=AccrualInterval(ValueState.PRESENT, '2025-12-15', '2025-12-20'),
                  payment_date=CanonicalValue(state=ValueState.NOT_APPLICABLE, reason_code='synthetic.reason'))
    ids = tuple(f.fact_id for f in facts)
    assert repo.register_observation(obs, ids) == WriteOutcome.CREATED
    stored = repo.get_observation(obs.observation_id)
    assert stored.observation == obs
    assert stored.fact_ids == tuple(sorted(ids))
    assert repo.register_observation(obs, tuple(reversed(ids))) == WriteOutcome.IDENTICAL
    with pytest.raises(ReproducibilityConflict):
        repo.register_observation(obs, ids[:1])
    with pytest.raises(ReproducibilityConflict):
        repo.register_observation(replace(obs, value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(17, 9))), ids)


@pytest.mark.parametrize('field,value', [('scope', 'invalid'), ('pay_behavior', 'invalid'),
                                        ('temporal_character', 'invalid'), ('payment_form', 'invalid'),
                                        ('economic_status', 'invalid'), ('eligibility', 'invalid'),
                                        ('confidence', 'invalid')])
def test_invalid_dimensions(store, field, value):
    result = register_evaluation(store)
    with pytest.raises(ValueError):
        replace(result.observations[0].observation, **{field: value})


@pytest.mark.parametrize('start,end', [('2026-02-30', '2026-03-01'), ('2026-03-02', '2026-03-01'), (None, '2026-03-01')])
def test_invalid_accrual(start, end):
    with pytest.raises(ValueError):
        AccrualInterval(ValueState.PRESENT, start, end)


def test_provenance_required_and_cannot_invent_inputs(store):
    repo, _, _, _, extraction, facts = store
    result = register_evaluation(store)
    obs = result.observations[0].observation
    with pytest.raises(ValueError):
        repo.register_observation(obs, ())
    extra = DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('other', facts[0].value))
    repo.register_fact(extra)
    with pytest.raises(ValueError):
        repo.register_observation(obs, (extra.fact_id,))


def test_assessment_manifest_rejects_forged_fact_content(store):
    repo, _, doc, _, _, facts = store
    rule = direct_totals_rule()
    repo.register_rule(rule)
    forged = replace(facts[0], value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(9, 0)))
    assessment = Assessment.from_facts(doc.document_id, rule.rule_id, (forged,), 'pending')
    with pytest.raises(ReproducibilityConflict):
        repo.register_assessment(assessment)


def test_atomic_interpretation_rollback(store):
    repo, conn, doc, _, _, facts = store
    result = evaluate_direct_totals(doc.document_id, facts, created_at=STAMP)
    with pytest.raises(ReproducibilityConflict):
        with repo.transaction():
            repo.register_rule(result.rule)
            repo.register_assessment(result.assessment)
            item = result.observations[0]
            repo.register_observation(item.observation, item.fact_ids)
            repo.register_observation(replace(item.observation, nature='different'), item.fact_ids)
    for table in ('rules', 'assessments', 'economic_observations', 'observation_facts'):
        assert conn.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,)


@pytest.mark.parametrize('table', ['rules', 'assessments', 'economic_observations', 'documentary_facts'])
@pytest.mark.parametrize('operation', ['DELETE', 'UPDATE'])
def test_restrict_deletion(store, table, operation):
    _, conn, _, _, _, _ = store
    register_evaluation(store)
    with pytest.raises(sqlite3.IntegrityError):
        if operation == 'DELETE':
            conn.execute(f'DELETE FROM {table}')
        else:
            key = {'rules': 'rule_id', 'assessments': 'assessment_id',
                   'economic_observations': 'observation_id', 'documentary_facts': 'fact_id'}[table]
            old = conn.execute(f'SELECT {key} FROM {table}').fetchone()[0]
            conn.execute(f'UPDATE {table} SET {key}=?', (old[:-64] + 'f'*64,))
    for child in ['assessments', 'economic_observations', 'observation_facts']:
        rows = conn.execute(f'PRAGMA foreign_key_list({child})').fetchall()
        assert rows and all(r[5:7] == ('RESTRICT', 'RESTRICT') for r in rows)


@pytest.mark.parametrize('upgrade', [False, True])
def test_v5_migration_integrity_reopening(tmp_path, upgrade):
    path = tmp_path / 'synthetic.sqlite'
    if upgrade:
        with open_database(path, mode='create', migrations=load_migrations()[:4]):
            pass
        with open_database(path) as db:
            assert db.status.pending_versions == (5,)
    with open_database(path, mode='migrate' if upgrade else 'create') as db:
        assert verify_schema(db.connection).current_version == 5
        tables = {r[0] for r in db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert tables == {'schema_migrations', 'persons', 'employers', 'corpora', 'source_files',
                          'file_locations', 'ingest_runs', 'ingest_items', 'logical_documents',
                          'document_versions', 'version_pages', 'extractions', 'documentary_facts',
                          'fact_pages', 'rules', 'assessments', 'economic_observations', 'observation_facts'}
        assert all(r[2] != 'REAL' for r in db.connection.execute('PRAGMA table_info(economic_observations)'))
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        history = db.connection.execute('SELECT * FROM schema_migrations').fetchall()
    with open_database(path, mode='migrate') as db:
        assert db.connection.execute('SELECT * FROM schema_migrations').fetchall() == history


@pytest.mark.parametrize('state', [ValueState.UNKNOWN, ValueState.UNRELIABLE, ValueState.TECHNICAL_NULL])
def test_usable_observation_cannot_claim_uncertain_value(store, state):
    result = register_evaluation(store)
    value = CanonicalValue(state=state, value=ExactDecimal(0, 0) if state == ValueState.UNRELIABLE else None,
                           reason_code='uncertain' if state == ValueState.UNRELIABLE else None)
    with pytest.raises(ValueError):
        replace(result.observations[0].observation, value=value)


@pytest.mark.parametrize('state', list(ValueState))
def test_observation_value_states_roundtrip_without_promotion(store, state):
    repo, _, _, _, _, _ = store
    result = register_evaluation(store)
    value = CanonicalValue(state=state, value=ExactDecimal(0, 0) if state in (ValueState.PRESENT, ValueState.UNRELIABLE) else None,
                           reason_code='synthetic.reason')
    key = 'state.' + state.value
    obs = replace(result.observations[0].observation,
                  observation_id=observation_id(result.assessment.assessment_id, key), observation_key=key,
                  value=value, economic_status='pending')
    repo.register_observation(obs, result.observations[0].fact_ids)
    assert repo.get_observation(obs.observation_id).observation.value == value
    with pytest.raises(ValueError):
        replace(obs, eligibility='candidate')


def test_present_zero_is_not_legacy_unreliable_zero(store):
    _, _, doc, _, _, facts = store
    explicit = replace(facts[0], value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0)))
    result = evaluate_direct_totals(doc.document_id, (explicit, facts[1]))
    gross = next(i.observation for i in result.observations if i.observation.magnitude == 'documentary_gross')
    assert gross.value == explicit.value
    assert gross.economic_status == 'usable'


def test_no_annual_gross_or_extra_pay_aggregation(store):
    _, _, doc, _, extraction, facts = store
    additional = (
        DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('nomina.prorrata_pagas_extra', CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(9999, 0)))),
        DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('nomina.tipo', CanonicalValue(state=ValueState.PRESENT, value='PAGA_EXTRA'))),
        DocumentaryFact.from_draft(extraction.extraction_id, FactDraft('nomina.periodo', CanonicalValue(state=ValueState.PRESENT, value='2026-01'))),
    )
    result = evaluate_direct_totals(doc.document_id, (*facts, *additional))
    assert {i.observation.magnitude for i in result.observations} == {'documentary_gross', 'documentary_net'}
    assert {i.observation.value for i in result.observations} == {f.value for f in facts}
    assert all(i.observation.liquidation_period.state == ValueState.UNKNOWN for i in result.observations)
    assert all(i.observation.settlement_context == 'unknown' for i in result.observations)


def test_assessment_rejects_input_from_another_document(store):
    repo, _, doc, _, _, facts = store
    other = replace(doc, document_id=document_id(doc.corpus_id, 'other-unit'), origin_key='other-unit')
    repo.register_document(other)
    rule = direct_totals_rule()
    repo.register_rule(rule)
    wrong = Assessment.from_facts(other.document_id, rule.rule_id, facts, 'pending')
    with pytest.raises(ValueError):
        repo.register_assessment(wrong)


def test_observation_and_links_rollback_if_link_insert_fails(store):
    repo, conn, doc, _, _, facts = store
    result = evaluate_direct_totals(doc.document_id, facts, created_at=STAMP)
    repo.register_rule(result.rule)
    repo.register_assessment(result.assessment)
    conn.execute("CREATE TRIGGER reject_link BEFORE INSERT ON observation_facts BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
    item = result.observations[0]
    with pytest.raises(sqlite3.IntegrityError):
        repo.register_observation(item.observation, item.fact_ids)
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone() == (0,)
    assert conn.execute('SELECT count(*) FROM observation_facts').fetchone() == (0,)


def test_mapping_rule_fingerprint_is_packaged_implementation_independent_of_cwd(tmp_path, monkeypatch):
    from importlib.resources import files

    from src.canonical import sha256_bytes

    expected = sha256_bytes(files('src').joinpath('economic_mapping.py').read_bytes())
    monkeypatch.chdir(tmp_path)
    assert direct_totals_rule().implementation_hash == expected


@pytest.mark.parametrize('temporal_field,bad_text', [('liquidation_period', '2026-13'), ('payment_date', '2026-02-30')])
def test_invalid_temporal_text(store, temporal_field, bad_text):
    result = register_evaluation(store)
    with pytest.raises(ValueError):
        replace(result.observations[0].observation,
                **{temporal_field: CanonicalValue(state=ValueState.PRESENT, value=bad_text)})


@pytest.mark.parametrize('currency', [None, CurrencyCode('EUR'), CurrencyCode('USD')])
def test_exact_coefficient_scale_and_currency_roundtrip(store, currency):
    repo, conn, _, _, _, _ = store
    result = register_evaluation(store)
    original = result.observations[0].observation
    obs = replace(original, observation_id=observation_id(result.assessment.assessment_id, 'exact'),
                  observation_key='exact', value=CanonicalValue(state=ValueState.PRESENT,
                  value=ExactDecimal(2**63-1, 9), currency=currency))
    repo.register_observation(obs, result.observations[0].fact_ids)
    assert repo.get_observation(obs.observation_id).observation.value == obs.value
    assert conn.execute('SELECT typeof(coefficient), typeof(scale) FROM economic_observations WHERE observation_id=?',
                        (obs.observation_id,)).fetchone() == ('integer', 'integer')
