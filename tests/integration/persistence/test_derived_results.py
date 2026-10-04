"""Synthetic exact cache results; no payroll KPI or economic aggregation."""
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from src.canonical import (
    CanonicalValue,
    CurrencyCode,
    ExactDecimal,
    ReproducibilityConflict,
    ValueState,
)
from src.canonical.derived import DerivedInput, DerivedResult
from src.canonical.economics import Rule
from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.persistence import load_migrations, open_database, verify_schema
from src.persistence.derived import DatasetRevisionConflict, DerivedRepository
from src.persistence.evidence import WriteOutcome
from src.persistence.state import CanonicalStateReader
from tests.integration.persistence.test_relations import unit

STAMP = '2026-01-01T00:00:00Z'


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = DerivedRepository(db.connection)
        person = Person(person_id(UUID(int=1)), 'synthetic')
        corpus = Corpus(corpus_id(UUID(int=2)), person.person_id, 'synthetic', 'v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        obs = []
        for key, value in [('a', '1.23'), ('b', '-0.23')]:
            _, _, o = unit((repo, db.connection, corpus), key,
                          value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal.from_text(value), currency=CurrencyCode('EUR')))
            obs.append(o)
        rule = Rule.define('synthetic', 'sum', '1', 'f'*64, created_at=STAMP)
        repo.register_rule(rule)
        inputs = tuple(DerivedInput('observation', o.observation_id) for o in obs)
        yield repo, db.connection, rule, inputs


def calculate(store, parameters=None):
    repo, _, rule, inputs = store
    captured = repo.capture_inputs(inputs)
    # Synthetic fixture only: no rule runner or economic sum in production.
    total = sum((value.value.to_decimal() for value in captured.values), Decimal(0))
    return DerivedResult.create(rule.rule_id, parameters or {'mode': 'synthetic'}, captured.dataset_revision,
        inputs, 'sum', 'synthetic_sum', CanonicalValue(state=ValueState.PRESENT,
        value=ExactDecimal.from_decimal(total), currency=CurrencyCode('EUR')), created_at=STAMP)


def test_exact_result_roundtrip_idempotence_provenance(store):
    repo, _, _, inputs = store
    result = calculate(store)
    assert result.value.value == ExactDecimal(1, 0)
    assert repo.publish(result) == WriteOutcome.CREATED
    assert repo.get_result(result.result_id) == result
    assert repo.publish(replace(result, created_at='2030-01-01T00:00:00Z')) == WriteOutcome.IDENTICAL
    assert repo.get_result(result.result_id).created_at == STAMP
    assert repo.freshness(result.result_id) == 'current'
    for link in repo.get_result(result.result_id).inputs:
        evidence = repo.get_observation(link.target_id)
        assert evidence.fact_ids
        fact = repo.get_fact(evidence.fact_ids[0])
        extraction = repo.get_extraction(fact.extraction_id)
        version = repo.get_version(extraction.version_id)
        assert repo.get_source_file(version.file_id) is not None
    assert set(repo.get_result(result.result_id).inputs) == set(inputs)


def test_cache_has_no_circular_revision(store):
    repo, conn, _, _ = store
    reader = CanonicalStateReader(conn)
    before, global_before = reader.read(), reader.read(include_derived_cache=True)
    result = calculate(store)
    repo.publish(result)
    assert reader.read() == before
    assert reader.read(include_derived_cache=True).fingerprint != global_before.fingerprint
    assert repo.capture_inputs(result.inputs).dataset_revision == result.dataset_revision
    assert repo.freshness(result.result_id) == 'current'
    cached = reader.read(include_derived_cache=True)
    # Synthetic direct SQL mutation tests exclusion, not a supported overwrite API.
    conn.execute('UPDATE derived_results SET coefficient=2')
    assert reader.read() == before
    assert reader.read(include_derived_cache=True) != cached


def test_parameters_and_inputs_order_are_deterministic(store):
    a = calculate(store, {'x': 1, 'y': ['a', True, None]})
    b = calculate(store, {'y': ['a', True, None], 'x': 1})
    assert a == b
    assert DerivedResult.create(a.rule_id, {'y': ['a', True, None], 'x': 1}, a.dataset_revision,
        tuple(reversed(a.inputs)), a.output_key, a.result_type, a.value, created_at=STAMP) == a
    assert calculate(store, {'x': 2}).result_id != a.result_id


def test_identity_excludes_output_and_conflicting_output_fails(store):
    repo, conn, _, _ = store
    result = calculate(store)
    repo.publish(result)
    before = tuple(conn.iterdump())
    with pytest.raises(ReproducibilityConflict):
        repo.publish(replace(result, value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(99, 0))))
    assert tuple(conn.iterdump()) == before


def test_changed_source_is_stale_and_inflight_publication_fails(store):
    repo, conn, _, _ = store
    result = calculate(store)
    repo.publish(result)
    conn.execute("UPDATE persons SET local_alias='changed'")
    assert repo.freshness(result.result_id) == 'stale'
    before = tuple(conn.iterdump())
    with pytest.raises(DatasetRevisionConflict):
        repo.publish(replace(result, output_key='other', result_id=DerivedResult.create(result.rule_id,
            {'mode': 'synthetic'}, result.dataset_revision, result.inputs, 'other', result.result_type,
            result.value, created_at=STAMP).result_id))
    assert tuple(conn.iterdump()) == before
    assert repo.get_result(result.result_id) == result


def test_change_during_calculation_prevents_any_publication(store):
    repo, conn, _, _ = store
    result = calculate(store)
    conn.execute("UPDATE source_files SET availability='withdrawn'")
    with pytest.raises(DatasetRevisionConflict):
        repo.publish(result)
    assert conn.execute('SELECT count(*) FROM derived_results').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM derived_inputs').fetchone()[0] == 0


def test_identical_registration_does_not_change_revision(store):
    repo, _, _, inputs = store
    captured = repo.capture_inputs(inputs)
    evidence = repo.get_observation(inputs[0].target_id)
    repo.register_observation(evidence.observation, evidence.fact_ids)
    assert repo.capture_inputs(inputs).dataset_revision == captured.dataset_revision


def test_invalid_result_is_not_publishable(store):
    repo, _, _, _ = store
    ready = calculate(store)
    invalid = replace(ready, status='invalid', value=CanonicalValue(state=ValueState.UNKNOWN))
    with pytest.raises(ValueError):
        repo.publish(invalid)
    assert repo.record_invalid(invalid) == WriteOutcome.CREATED
    assert repo.freshness(invalid.result_id) == 'invalid'


def test_fact_input_and_unknown_currency(store):
    repo, _, rule, inputs = store
    fact_id = repo.get_observation(inputs[0].target_id).fact_ids[0]
    links = (DerivedInput('fact', fact_id),)
    captured = repo.capture_inputs(links)
    result = DerivedResult.create(rule.rule_id, {}, captured.dataset_revision, links, 'copy', 'synthetic_copy',
                                  CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0, 0)), created_at=STAMP)
    repo.publish(result)
    assert repo.get_result(result.result_id).value.currency is None


@pytest.mark.parametrize('case', ['empty', 'duplicate', 'float', 'ready_unknown'])
def test_invalid_contracts_rejected(store, case):
    result = calculate(store)
    with pytest.raises((ValueError, TypeError)):
        if case == 'empty':
            replace(result, inputs=())
        elif case == 'duplicate':
            replace(result, inputs=result.inputs*2)
        elif case == 'float':
            calculate(store, {'x': 0.1})
        else:
            replace(result, value=CanonicalValue(state=ValueState.UNKNOWN))


def test_publication_rolls_back_as_part_of_outer_transaction(store):
    repo, conn, _, _ = store
    result = calculate(store)
    with pytest.raises(RuntimeError):
        with repo.transaction():
            repo.publish(result)
            raise RuntimeError('synthetic rollback')
    assert conn.execute('SELECT count(*) FROM derived_results').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM derived_inputs').fetchone()[0] == 0


@pytest.mark.parametrize('upgrade', [False, True])
def test_v8_migration_integrity(tmp_path, upgrade):
    path = tmp_path/'test.sqlite'
    if upgrade:
        with open_database(path, mode='create', migrations=load_migrations()[:7]):
            pass
    with open_database(path, mode='migrate' if upgrade else 'create') as db:
        assert verify_schema(db.connection).current_version == 8
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        before = tuple(db.connection.iterdump())
    with open_database(path, mode='migrate') as db:
        assert tuple(db.connection.iterdump()) == before


def test_foreign_keys_restrict_source_and_rule_deletion(store):
    import sqlite3
    repo, conn, rule, inputs = store
    result = calculate(store)
    repo.publish(result)
    for sql, key in [('DELETE FROM rules WHERE rule_id=?', rule.rule_id),
                     ('DELETE FROM economic_observations WHERE observation_id=?', inputs[0].target_id)]:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql, (key,))


@pytest.mark.parametrize('text', ['0', '-201.53', '0.000000001', '123456789.123456789'])
def test_exact_decimal_scales_sign_and_zero(store, text):
    repo, _, _, _ = store
    result = replace(calculate(store), value=CanonicalValue(state=ValueState.PRESENT,
                     value=ExactDecimal.from_text(text), currency=CurrencyCode('EUR')))
    repo.publish(result)
    assert repo.get_result(result.result_id).value == result.value


@pytest.mark.parametrize('change', ['rule', 'revision', 'inputs', 'key'])
def test_calculation_identity_components(store, change):
    original = calculate(store)
    other = DerivedResult.create(
        'rule:sha256:'+'a'*64 if change == 'rule' else original.rule_id,
        {'mode': 'synthetic'}, 'b'*64 if change == 'revision' else original.dataset_revision,
        original.inputs[:1] if change == 'inputs' else original.inputs,
        'other' if change == 'key' else original.output_key, original.result_type, original.value,
        created_at=STAMP)
    assert other.result_id != original.result_id


def test_unknown_input_cannot_publish(store):
    repo, conn, rule, _ = store
    result = DerivedResult.create(rule.rule_id, {}, repo.dataset_revision(),
        (DerivedInput('fact', 'fact:sha256:'+'f'*64),), 'unknown', 'synthetic',
        CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(1, 0)), created_at=STAMP)
    with pytest.raises(ValueError, match='Unknown documentary input'):
        repo.publish(result)
    assert conn.execute('SELECT count(*) FROM derived_results').fetchone()[0] == 0


def test_sql_input_fk_and_exclusive_target_constraints(store):
    import sqlite3
    repo, conn, _, _ = store
    result = calculate(store)
    repo.publish(result)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT INTO derived_inputs(result_id,input_id,fact_id) VALUES (?,?,?)',
                     (result.result_id, 'fact:sha256:'+'e'*64, 'fact:sha256:'+'e'*64))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('DELETE FROM derived_results WHERE result_id=?', (result.result_id,))
    for table in ('derived_results', 'derived_inputs'):
        assert all(row[5:7] == ('RESTRICT', 'RESTRICT') for row in conn.execute(f'PRAGMA foreign_key_list({table})'))


def test_cache_can_be_removed_and_reconstructed_without_changing_source_revision(store):
    repo, conn, _, _ = store
    result = calculate(store)
    source = repo.dataset_revision()
    repo.publish(result)
    audit = CanonicalStateReader(conn).read(include_derived_cache=True)
    # Explicit synthetic cache eviction, never a source or automatic stale deletion.
    with repo.transaction():
        conn.execute('DELETE FROM derived_inputs')
        conn.execute('DELETE FROM derived_results')
    assert repo.dataset_revision() == source
    rebuilt = calculate(store)
    assert rebuilt == result
    repo.publish(rebuilt)
    assert CanonicalStateReader(conn).read(include_derived_cache=True) == audit


def test_v8_fingerprint_scopes_are_explicit(store):
    reader = CanonicalStateReader(store[1])
    source = reader.read()
    audit = reader.read(include_derived_cache=True)
    assert b'canonical-persisted-state/v2' in source.canonical_content
    assert b'global-with-cache' in audit.canonical_content
    assert 'derived_results' not in dict(source.table_counts)
    assert 'derived_results' in dict(audit.table_counts)
    assert len(source.table_counts) == 21 and len(audit.table_counts) == 23
    assert source.fingerprint != audit.fingerprint


def test_changed_fact_invalidates_without_touching_cache(store):
    repo, conn, _, _ = store
    result = calculate(store)
    repo.publish(result)
    cache_before = conn.execute('SELECT * FROM derived_results').fetchall()
    conn.execute('UPDATE documentary_facts SET coefficient=999 WHERE fact_id=(SELECT min(fact_id) FROM documentary_facts)')
    assert repo.freshness(result.result_id) == 'stale'
    assert conn.execute('SELECT * FROM derived_results').fetchall() == cache_before


def test_migration_checksum_protected(store):
    from src.persistence import MigrationChecksumError
    store[1].execute('UPDATE schema_migrations SET checksum=? WHERE version=8', ('d'*64,))
    with pytest.raises(MigrationChecksumError):
        verify_schema(store[1])
