"""Identity and physical evidence contracts, independent of SQLite."""
from dataclasses import replace
from uuid import UUID

import pytest

from src.canonical import ReproducibilityConflict, sha256_bytes
from src.canonical.evidence import (
    Corpus,
    Employer,
    FileLocation,
    IngestItem,
    IngestRun,
    Person,
    SourceFile,
    corpus_id,
    employer_id,
    person_id,
    source_file_id,
)

SEED = UUID('00000000-0000-0000-0000-000000000001')
SHA = sha256_bytes(b'abc')


def test_identity_policies():
    assert person_id(SEED) == person_id(SEED)
    assert person_id() != person_id()
    assert employer_id('ES', 'A123') == employer_id('ES', 'A123')
    assert employer_id('ES', 'A123') != employer_id('PT', 'A123')
    assert employer_id('ES', seed=SEED) == employer_id('ES', seed=SEED)
    assert corpus_id(SEED).namespace == 'corpus'
    assert source_file_id(SHA).namespace == 'file'
    assert SHA == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


@pytest.mark.parametrize('alias', ['', '  '])
def test_person_alias_required(alias):
    with pytest.raises(ValueError):
        Person(person_id(), alias)


def test_employer_name_does_not_define_identity():
    first = Employer(employer_id('ES', 'A123'), 'ES', 'A123', 'First')
    assert replace(first, display_name='Second').employer_id == first.employer_id
    with pytest.raises(ValueError):
        replace(first, employer_id=employer_id('ES', 'B456'))


@pytest.mark.parametrize('changes', [
    {'byte_size': -1}, {'byte_size': True}, {'page_count': 0}, {'page_count': -1},
    {'page_count': True}, {'availability': 'missing'}, {'sha256': 'A'*64},
    {'file_id': source_file_id('f'*64)}, {'media_type': ''},
])
def test_source_file_validation(changes):
    record = SourceFile(source_file_id(SHA), SHA, 3, 'application/pdf')
    with pytest.raises((ValueError, TypeError)):
        replace(record, **changes)


@pytest.mark.parametrize('path', ['/private/a.pdf', '../a.pdf', 'a/../b.pdf',
                                 'C:/secret/a.pdf', 'a\\b.pdf', '', './a.pdf', 'a//b.pdf'])
def test_location_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        FileLocation(corpus_id(), path, source_file_id(SHA), 'a.pdf')


def test_plan_is_versioned_deterministic_and_rejects_floats():
    a = IngestRun.from_plan({'b': [1, None], 'a': 'ñ'})
    b = IngestRun.from_plan({'a': 'ñ', 'b': [1, None]})
    assert a.run_id == b.run_id
    assert a.plan_json == b.plan_json
    assert '"version":1' in a.plan_json
    with pytest.raises(TypeError):
        IngestRun.from_plan({'x': 1.5})
    with pytest.raises(ReproducibilityConflict):
        replace(a, plan_json=b.plan_json.replace('ñ', 'n'))


@pytest.mark.parametrize('timestamp', ['2026-01-01', '2026-01-01T00:00:00',
                                       '2026-01-01T00:00:00+02:00'])
def test_timestamps_require_utc(timestamp):
    with pytest.raises(ValueError):
        Person(person_id(), 'local', created_at=timestamp)


def test_errors_are_sanitized_without_persisting_raw_input():
    run = IngestRun.from_plan([])
    item = IngestItem(run.run_id, '1', corpus_id(), 'a.pdf', status='failed',
                      reason_code='read_failed', error_detail='Traceback /Users/secret DNI 123')
    assert item.error_detail == 'Details omitted; see reason_code.'
    assert 'secret' not in item.error_detail


def test_wrong_namespaces_rejected():
    with pytest.raises(ValueError):
        Person(corpus_id(), 'local')
    with pytest.raises(ValueError):
        Corpus(corpus_id(), employer_id('ES', 'A'), 'label', 'manifest/v1')


@pytest.mark.parametrize('node', [['nonsense'], ['int', '01'], ['bool', 1],
                                 ['map', [['a', ['null']], ['a', ['null']]]]])
def test_invalid_canonical_plan_tree_rejected(node):
    import json

    from src.canonical.evidence import ingest_run_id

    payload = json.dumps({'contract': 'canonical', 'version': 1, 'value': node},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = sha256_bytes(payload.encode())
    with pytest.raises(ValueError):
        IngestRun(ingest_run_id(digest), digest, 1, payload)


@pytest.mark.parametrize('status', ['pending', 'processed', 'skipped', 'failed'])
def test_all_item_states(status):
    run = IngestRun.from_plan([])
    item = IngestItem(run.run_id, '1', corpus_id(), 'a.pdf', status=status,
                      file_id=source_file_id(SHA) if status == 'processed' else None,
                      reason_code='test_reason' if status in ('skipped', 'failed') else None)
    assert item.status == status


@pytest.mark.parametrize('changes', [{'status': 'invalid'}, {'status': 'processed'},
                                    {'status': 'failed'}, {'status': 'skipped'},
                                    {'reason_code': '/private/path'},
                                    {'error_detail': 'raw'}, {'expected_sha256': 'invalid'}])
def test_invalid_item_states(changes):
    item = IngestItem(IngestRun.from_plan([]).run_id, '1', corpus_id(), 'a.pdf')
    with pytest.raises(ValueError):
        replace(item, **changes)


@pytest.mark.parametrize('availability', ['available', 'not_located', 'withdrawn'])
def test_all_availability_states(availability):
    assert SourceFile(source_file_id(SHA), SHA, 0, 'application/pdf',
                      availability=availability).availability == availability


@pytest.mark.parametrize('changes', [{'status': 'complete'}, {'status': 'bogus'},
                                    {'contract_version': True}, {'contract_version': 2},
                                    {'finished_at': '2030-01-01T00:00:00Z'}])
def test_invalid_runs(changes):
    with pytest.raises(ValueError):
        replace(IngestRun.from_plan({}), **changes)
