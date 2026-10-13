"""Closed-inventory projection with synthetic payloads, never private documents."""
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from src.alten_projection import FIELDS, NAME, finalize_alten
from src.canonical import ExactDecimal, canonical_sha256
from src.canonical.certification import DocumentarySupport, certify_observation
from src.canonical.economics import fact_fingerprint
from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical_ingestion import CorpusInput, ingest, inventory
from src.canonical_inspection import CanonicalInspector
from src.ingestion_processors import AltenPDF
from src.persistence import open_database
from src.persistence.relations import RelationRepository
from src.persistence.state import CanonicalStateReader
from tests.integration.persistence.test_alten_canonical import legacy


class SyntheticAlten:
    revision = 'synthetic-projection/v1'

    def __init__(self, net='789.123456789'):
        self.net = net

    def prepare(self, data, filename):
        from src.canonical import sha256_bytes
        period, version = legacy(sha256_bytes(data), amount=1234)
        payload = json.loads(version['payload'])
        payload.update(empresa='ALTEN synthetic', anio=2025, mes=1)
        # Different files represent discrepant versions; same logical identity.
        payload['total_devengado'] += int(data)
        version['payload'] = json.dumps(payload).replace('"liquido_percibir": 0',
                                                         '"liquido_percibir": ' + self.net)
        return AltenPDF(1, (period,), (version,))


@pytest.fixture
def snapshot(tmp_path):
    with open_database(':memory:', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'synthetic/v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        bindings = (CorpusInput(corpus.corpus_id, tmp_path, 'synthetic'),)
        yield repo, db.connection, bindings, tmp_path


def prepare(snapshot, count=1, processor=None):
    repo, _, bindings, root = snapshot
    for n in range(count):
        (root / f'{n}.pdf').write_bytes(str(n).encode())
    sources = inventory(bindings)
    processors = {'synthetic': processor or SyntheticAlten()}
    result = ingest(repo, bindings, processors, sources=sources)
    assert result.failed == 0
    return result, sources, processors


def project(snapshot, result, sources):
    _, connection, bindings, _ = snapshot
    finalize_alten(connection, result.run_id, bindings, sources)


def test_single_version_exact_values_lineage_originals_and_explorer(snapshot):
    repo, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot)
    original_rows = conn.execute('SELECT * FROM documentary_facts').fetchall()
    original_pages = conn.execute('SELECT * FROM fact_pages').fetchall()
    project(snapshot, result, sources)
    assert set(original_rows) <= set(conn.execute('SELECT * FROM documentary_facts'))
    assert set(original_pages) <= set(conn.execute('SELECT * FROM fact_pages'))
    projected_id = conn.execute('SELECT extraction_id FROM extractions WHERE extractor_name=?', (NAME,)).fetchone()[0]
    projected = {f.fact_key: f for f in repo.get_extraction_facts(projected_id)}
    for field in FIELDS:
        key = 'nomina.' + field
        original_id = projected[f'projection/{field}/source_fact'].value.value
        original = repo.get_fact(original_id)
        assert projected[key].value == original.value
        assert projected[f'projection/{field}/fingerprint'].value.value == fact_fingerprint(original)
        assert [p.page_number for p in repo.get_fact_pages(projected[key].fact_id)] == [1]
        assert projected[key].fact_id != original_id
    net = projected['nomina.liquido_percibir'].value
    assert net.value.to_decimal() == Decimal('789.123456789')
    assert net.currency is None
    assert projected['projection/source_content_hash'].value.value == repo.get_extraction(
        projected['projection/source_extraction'].value.value).content_hash
    rows = CanonicalInspector(conn).documents(company='ALTEN synthetic', year=2025, month=1)
    assert len(rows) == 1
    assert rows[0]['gross']['status'] == rows[0]['net']['status'] == 'certified'
    assert rows[0]['net']['amount'] == net.value
    assert conn.execute('SELECT DISTINCT eligibility FROM economic_observations').fetchall() == [('evidence_only',)]
    assert conn.execute('SELECT count(*) FROM document_relations').fetchone()[0] == 0


@pytest.mark.parametrize('count', [2, 3])
def test_all_versions_across_files_known_before_promotion(snapshot, count):
    _, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot, count)
    before = CanonicalStateReader(conn).read()
    project(snapshot, result, sources)
    assert CanonicalStateReader(conn).read() == before
    assert conn.execute('SELECT count(*) FROM logical_documents').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM document_versions').fetchone()[0] == count
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0


@pytest.mark.parametrize('net', ['null', '0'])
def test_absent_or_unreliable_values_remain_uncertified(snapshot, net):
    repo, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot, processor=SyntheticAlten(net))
    project(snapshot, result, sources)
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0
    ext = conn.execute('SELECT extraction_id FROM extractions WHERE extractor_name=?', (NAME,)).fetchone()[0]
    facts = {f.fact_key: f for f in repo.get_extraction_facts(ext)}
    original = repo.get_fact(facts['projection/liquido_percibir/source_fact'].value.value)
    assert facts['nomina.liquido_percibir'].value == original.value


def test_certification_rejects_altered_support(snapshot):
    repo, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot)
    project(snapshot, result, sources)
    for (identity,) in conn.execute('SELECT observation_id FROM economic_observations'):
        evidence = repo.get_observation(identity)
        assessment = repo.get_assessment(evidence.observation.assessment_id)
        facts = tuple(repo.get_fact(i.fact_id) for i in assessment.inputs)
        extraction = repo.get_extraction(facts[0].extraction_id)
        support = DocumentarySupport(repo.get_document(assessment.document_id),
            repo.get_version(extraction.version_id), extraction, repo.get_rule(assessment.rule_id), assessment, facts)
        assert certify_observation(evidence, support).value_status == 'certified'
        altered = tuple(replace(f, value=replace(f.value, value=ExactDecimal(999, 0)))
                        if f.fact_id in evidence.fact_ids else f for f in facts)
        assert certify_observation(evidence, replace(support, facts=altered)).value_status == 'blocked'


def test_reingestion_and_finalization_idempotent(snapshot):
    repo, conn, bindings, _ = snapshot
    result, sources, processors = prepare(snapshot)
    project(snapshot, result, sources)
    before = CanonicalStateReader(conn).read(include_operational_metadata=True)
    replay = ingest(repo, bindings, processors, sources=sources)
    assert replay == result
    project(snapshot, replay, sources)
    assert CanonicalStateReader(conn).read(include_operational_metadata=True) == before


@pytest.mark.parametrize('change', ['addition', 'deletion', 'modification', 'explicit_exclusion', 'partial_run', 'unknown_skip'])
def test_incomplete_inventory_never_promoted(snapshot, change):
    _, conn, _, root = snapshot
    result, sources, _ = prepare(snapshot)
    if change == 'addition':
        (root/'later.pdf').write_bytes(b'1')
    elif change == 'deletion':
        (root/'0.pdf').unlink()
    elif change == 'modification':
        (root/'0.pdf').write_bytes(b'1')
    elif change == 'explicit_exclusion':
        sources = (replace(sources[0], skip_reason='annual_certificate'),)
    elif change == 'partial_run':
        conn.execute("UPDATE ingest_runs SET status='partial'")
    else:
        conn.execute("UPDATE ingest_items SET status='skipped',reason_code='no_extractable_text'")
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError):
        project(snapshot, result, sources)
    assert CanonicalStateReader(conn).read() == before


def test_corrupt_original_fingerprint_blocks_projection(snapshot):
    _, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot)
    conn.execute('UPDATE extractions SET content_hash=?', ('a'*64,))
    with pytest.raises(ValueError, match='fingerprint'):
        project(snapshot, result, sources)
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0


def test_second_ingestion_run_requires_fresh_rebuild(snapshot):
    repo, conn, bindings, root = snapshot
    result, sources, processors = prepare(snapshot)
    project(snapshot, result, sources)
    (root/'second.pdf').write_bytes(b'1')
    new_sources = inventory(bindings)
    second = ingest(repo, bindings, processors, sources=new_sources)
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError, match='fresh-build'):
        project(snapshot, second, new_sources)
    assert CanonicalStateReader(conn).read() == before


def test_projection_content_fingerprint(snapshot):
    repo, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot)
    project(snapshot, result, sources)
    for (identity,) in conn.execute('SELECT extraction_id FROM extractions'):
        facts = repo.get_extraction_facts(identity)
        assert repo.get_extraction(identity).content_hash == canonical_sha256({f.fact_key: f.value for f in facts})


@pytest.mark.parametrize('count', [1, 2, 3])
def test_builder_finalizes_only_after_all_pdfs(tmp_path, monkeypatch, count):
    import src.canonical_build as module
    from src.canonical_build import BuildConfig, CorpusBuild, build
    person = Person(person_id(), 'synthetic')
    corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'synthetic/v1')
    root = tmp_path/'inputs'
    root.mkdir()
    for n in range(count):
        (root/f'{n}.pdf').write_bytes(str(n).encode())
    monkeypatch.setattr(module, 'AltenProcessor', SyntheticAlten)
    config = BuildConfig(person, (CorpusBuild(corpus, root, 'alten', None, ()),), 'synthetic/v1')
    output = tmp_path/'candidate.sqlite'
    report = build(config, output)
    assert report.ingestion.processed == count
    with open_database(output, mode='verify') as db:
        assert db.connection.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == (2 if count == 1 else 0)
        assert db.connection.execute('SELECT count(*) FROM document_versions').fetchone()[0] == count


def test_builder_changed_inventory_is_not_published(tmp_path, monkeypatch):
    import src.canonical_build as module
    from src.canonical_build import BuildConfig, CorpusBuild, build
    person = Person(person_id(), 'synthetic')
    corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'synthetic/v1')
    root = tmp_path/'inputs'
    root.mkdir()
    (root/'first.pdf').write_bytes(b'0')
    original_ingest = module.ingest
    def changed_inventory(*args, **kwargs):
        result = original_ingest(*args, **kwargs)
        (root/'later.pdf').write_bytes(b'1')
        return result
    monkeypatch.setattr(module, 'ingest', changed_inventory)
    monkeypatch.setattr(module, 'AltenProcessor', SyntheticAlten)
    config = BuildConfig(person, (CorpusBuild(corpus, root, 'alten', None, ()),), 'synthetic/v1')
    output = tmp_path/'candidate.sqlite'
    with pytest.raises(ValueError, match='complete inventory'):
        build(config, output)
    assert not output.exists()
    assert not list(tmp_path.glob('.canonical-build-*'))


@pytest.mark.parametrize('count', [2, 3])
def test_versions_on_different_pages_are_not_selected(snapshot, count):
    class MultiplePages(SyntheticAlten):
        def prepare(self, data, filename):
            prepared = super().prepare(data, filename)
            version = prepared.versions[0]
            # Even equal totals on several pages do not justify selecting one.
            versions = tuple(dict(version, page_number=page,
                version_key=f"sha256:{version['pdf_sha256']}:page:{page}") for page in range(1, count+1))
            return AltenPDF(count, prepared.periods, versions)
    _, conn, _, _ = snapshot
    result, sources, _ = prepare(snapshot, processor=MultiplePages())
    project(snapshot, result, sources)
    assert conn.execute('SELECT count(*) FROM document_versions').fetchone()[0] == count
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0
    assert conn.execute('SELECT DISTINCT status FROM assessments').fetchall() == [('ambiguous',)]
