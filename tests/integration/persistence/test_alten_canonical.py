"""Synthetic legacy ALTEN bridge: documentary evidence only."""
import json
from dataclasses import replace

import pytest

from src.alten_canonical import integrate_alten
from src.candidate_selection import select_candidates
from src.canonical import ReproducibilityConflict, ValueState
from src.canonical.evidence import (
    Corpus,
    FileLocation,
    Person,
    SourceFile,
    corpus_id,
    person_id,
    source_file_id,
)
from src.persistence import open_database, verify_schema
from src.persistence.relations import RelationRepository

STAMP = '2026-01-01T00:00:00Z'


@pytest.fixture
def store():
    with open_database(':memory:', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'legacy-alten/v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        yield repo, db.connection, corpus


def source(corpus, digest='a'*64):
    file = SourceFile(source_file_id(digest), digest, 42, 'application/pdf', page_count=2)
    location = FileLocation(corpus.corpus_id, digest + '.pdf', file.file_id, digest + '.pdf')
    return file, location


def legacy(digest='a'*64, page=1, amount=100):
    period = dict(period_key='CIF|2025-01-01|2025-01-31|nomina_ordinaria', cif='CIF',
                  fecha_inicio='2025-01-01', fecha_fin='2025-01-31', tipo='nomina_ordinaria',
                  resolution_status='UNRESOLVED')
    payload = dict(cif='CIF', fecha_inicio=period['fecha_inicio'], fecha_fin=period['fecha_fin'],
                   tipo=period['tipo'], total_devengado=amount, liquido_percibir=0,
                   base_irpf=None, conceptos=[{'codigo': '1', 'importe': amount},
                                             {'codigo': '1', 'importe': -2.5}])
    version = dict(period_key=period['period_key'], version_key=f'sha256:{digest}:page:{page}',
                   pdf_sha256=digest, page_number=page, source_filename=digest+'.pdf',
                   payload=json.dumps(payload))
    return period, version


def apply(store, versions=None, periods=None, sources=None, stamp=STAMP):
    repo, _, corpus = store
    p, v = legacy()
    return integrate_alten(repo, corpus.corpus_id, periods or [p], versions or [v],
                           sources or [source(corpus)], created_at=stamp)


def test_evidence_state_provenance_and_idempotence(store):
    repo, conn, _ = store
    result = apply(store)
    assert (len(result.document_ids), len(result.version_ids)) == (1, 1)
    assert {a.status for a in repo.list_assessments()} == {'pending'}
    assert not select_candidates(repo).candidates
    facts = repo.get_extraction_facts(result.extraction_ids[0])
    by_key = {f.fact_key: f for f in facts}
    assert by_key['payload/total_devengado'].value.value.to_decimal() == 100
    assert by_key['payload/liquido_percibir'].value.state == ValueState.UNRELIABLE
    assert by_key['payload/base_irpf'].value.state == ValueState.UNKNOWN
    assert 'payload/conceptos/0/importe' in by_key and 'payload/conceptos/1/importe' in by_key
    assert len(repo.get_fact_pages(by_key['payload/total_devengado'].fact_id)) == 1
    assert not repo.get_fact_pages(by_key['legacy/resolution_status'].fact_id)
    before = tuple(conn.iterdump())
    assert apply(store, stamp='2030-01-01T00:00:00Z') == result
    assert tuple(conn.iterdump()) == before
    assert verify_schema(conn).current_version == 6


def test_divergent_versions_never_selected_and_order_independent(store):
    p, a = legacy()
    _, b = legacy(page=2, amount=200)
    result = apply(store, [a, b], [p])
    assert len(result.document_ids) == 1 and len(result.version_ids) == 2
    assert {a.status for a in store[0].list_assessments()} == {'ambiguous'}
    assert not select_candidates(store[0]).candidates
    before = tuple(store[1].iterdump())
    assert apply(store, [b, a], [p]) == result
    assert tuple(store[1].iterdump()) == before


def test_conflict_rolls_back_entire_batch(store):
    apply(store)
    p, changed = legacy(amount=999)
    _, new = legacy('b'*64)
    before = tuple(store[1].iterdump())
    with pytest.raises(ReproducibilityConflict):
        apply(store, [new, changed], [p], [source(store[2]), source(store[2], 'b'*64)])
    assert tuple(store[1].iterdump()) == before


@pytest.mark.parametrize('change', ['resolved', 'missing_file', 'bad_key', 'bad_period', 'no_versions', 'selected'])
def test_invalid_or_resolved_input_fails_without_writes(store, change):
    p, v = legacy()
    sources = [source(store[2])]
    if change == 'resolved':
        p['resolution_status'] = 'RESOLVED'
    if change == 'missing_file':
        sources = [source(store[2], 'b'*64)]
    if change == 'bad_key':
        v['version_key'] = 'invalid'
    if change == 'bad_period':
        p['cif'] = 'other'
    if change == 'no_versions':
        v['period_key'] = 'missing'
    if change == 'selected':
        p['selected_version_key'] = v['version_key']
    before = tuple(store[1].iterdump())
    with pytest.raises(ValueError):
        apply(store, [v], [p], sources)
    assert tuple(store[1].iterdump()) == before


def test_precision_not_reconstructed_and_original_payload_preserved(store):
    p, v = legacy()
    v['payload'] = v['payload'].replace('100', '100.123456789123')
    result = apply(store, [v], [p])
    facts = {f.fact_key: f for f in store[0].get_extraction_facts(result.extraction_ids[0])}
    assert facts['payload/total_devengado'].value.state == ValueState.UNRELIABLE
    assert facts['payload/total_devengado'].value.value == '100.123456789123'
    assert facts['legacy/payload'].value.value == v['payload']


def test_inventory_conflict_is_atomic(store):
    apply(store)
    file, location = source(store[2])
    before = tuple(store[1].iterdump())
    with pytest.raises(ReproducibilityConflict):
        apply(store, sources=[(replace(file, byte_size=43), location)])
    assert tuple(store[1].iterdump()) == before


def test_negative_amount_unknown_currency_and_two_groups(store):
    p, v = legacy(amount=-201.53)
    other = dict(p, fecha_inicio='2025-02-01', fecha_fin='2025-02-28')
    other['period_key'] = '|'.join(other[k] for k in ('cif', 'fecha_inicio', 'fecha_fin', 'tipo'))
    _, second = legacy(page=2)
    payload = json.loads(second['payload'])
    payload.update({k: other[k] for k in ('fecha_inicio', 'fecha_fin')})
    second.update(period_key=other['period_key'], payload=json.dumps(payload))
    result = apply(store, [v, second], [p, other])
    assert len(result.document_ids) == len(result.version_ids) == 2
    amounts = [f.value for identity in result.extraction_ids for f in store[0].get_extraction_facts(identity)
               if f.fact_key == 'payload/total_devengado']
    assert {str(v.value.to_decimal()) for v in amounts} == {'-201.53', '100'}
    assert all(v.currency is None for v in amounts)


@pytest.mark.parametrize('payload', ['{"cif":1,"cif":2}', '{"amount": NaN}', '[]'])
def test_invalid_json_fails_atomically(store, payload):
    p, v = legacy()
    v['payload'] = payload
    before = tuple(store[1].iterdump())
    with pytest.raises(ValueError):
        apply(store, [v], [p])
    assert tuple(store[1].iterdump()) == before


def test_fact_pointer_escaping_and_bool_preserved(store):
    p, v = legacy()
    payload = json.loads(v['payload'])
    payload['a/b~c'] = True
    v['payload'] = json.dumps(payload)
    result = apply(store, [v], [p])
    facts = {f.fact_key: f for f in store[0].get_extraction_facts(result.extraction_ids[0])}
    assert facts['payload/a~1b~0c'].value.value == 'true'
