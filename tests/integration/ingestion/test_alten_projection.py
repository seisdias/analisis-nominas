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


def test_explicit_resolution_projects_only_selected_version(snapshot):
    """A reviewed version selection unlocks projection without deleting evidence."""
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)
    document = conn.execute(
        'SELECT document_id FROM logical_documents'
    ).fetchone()[0]
    versions = repo.get_document_versions(document)
    assert len(versions) == 2

    from src.alten_resolutions import VersionResolution

    resolution = VersionResolution(
        document_id=document,
        version_id=versions[1].version_id,
        reason='Reviewed against independent payment evidence',
        expected_version_ids=tuple(v.version_id for v in versions),
    )
    finalize_alten(
        conn, result.run_id, bindings, sources,
        resolutions=(resolution,),
    )

    assert conn.execute(
        'SELECT count(*) FROM document_versions'
    ).fetchone()[0] == 2
    assert conn.execute(
        'SELECT count(*) FROM economic_observations'
    ).fetchone()[0] == 2
    assert conn.execute(
        'SELECT DISTINCT eligibility FROM economic_observations'
    ).fetchall() == [('evidence_only',)]



def test_unknown_resolution_document_blocks_projection(snapshot):
    """A resolution for an unknown document must never be ignored."""
    from src.alten_resolutions import VersionResolution

    _, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)

    before = CanonicalStateReader(conn).read()

    resolution = VersionResolution(
        document_id='unknown-document',
        version_id='unknown-version',
        reason='Synthetic invalid selection',
        expected_version_ids=('unknown-version',),
    )

    with pytest.raises(ValueError, match='resolution'):
        finalize_alten(
            conn, result.run_id, bindings, sources,
            resolutions=(resolution,),
        )

    assert CanonicalStateReader(conn).read() == before


def test_conflicting_resolutions_block_projection(snapshot):
    """Two selections for one document must fail without changing canonical state."""
    from src.alten_resolutions import VersionResolution

    _, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)

    document_id = conn.execute(
        'SELECT document_id FROM logical_documents LIMIT 1'
    ).fetchone()[0]
    version_ids = [
        row[0]
        for row in conn.execute(
            'SELECT version_id FROM document_versions WHERE document_id = ? '
            'ORDER BY version_id',
            (document_id,),
        )
    ]
    assert len(version_ids) == 2

    resolutions = tuple(
        VersionResolution(
            document_id=document_id,
            version_id=version_id,
            reason='Synthetic conflicting selection',
            expected_version_ids=tuple(version_ids),
        )
        for version_id in version_ids
    )

    before = CanonicalStateReader(conn).read()

    with pytest.raises(ValueError, match='Multiple ALTEN resolutions'):
        finalize_alten(
            conn, result.run_id, bindings, sources,
            resolutions=resolutions,
        )

    assert CanonicalStateReader(conn).read() == before


def test_unavailable_resolution_version_blocks_projection(snapshot):
    """A selection must reference a version belonging to its document."""
    from src.alten_resolutions import VersionResolution

    _, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)

    document_id = conn.execute(
        'SELECT document_id FROM logical_documents LIMIT 1'
    ).fetchone()[0]

    resolution = VersionResolution(
        document_id=document_id,
        version_id='sha256:nonexistent:page:1',
        reason='Synthetic invalid version',
        expected_version_ids=('sha256:nonexistent:page:1',),
    )

    before = CanonicalStateReader(conn).read()

    with pytest.raises(ValueError, match='unavailable version'):
        finalize_alten(
            conn, result.run_id, bindings, sources,
            resolutions=(resolution,),
        )

    assert CanonicalStateReader(conn).read() == before


def test_resolution_rejects_stale_version_inventory(snapshot):
    """A reviewed selection must reject a changed candidate-version set."""
    from src.alten_resolutions import VersionResolution

    _, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)

    document_id = conn.execute(
        'SELECT document_id FROM logical_documents LIMIT 1'
    ).fetchone()[0]
    version_ids = tuple(
        row[0] for row in conn.execute(
            'SELECT version_id FROM document_versions '
            'WHERE document_id=? ORDER BY version_id',
            (document_id,),
        )
    )
    assert len(version_ids) == 2

    resolution = VersionResolution(
        document_id=document_id,
        version_id=version_ids[0],
        reason='Reviewed against independent payment evidence',
        expected_version_ids=(version_ids[0],),
    )

    before = CanonicalStateReader(conn).read()

    with pytest.raises(ValueError, match='stale|version inventory'):
        finalize_alten(
            conn, result.run_id, bindings, sources,
            resolutions=(resolution,),
        )

    assert CanonicalStateReader(conn).read() == before


def resolution_for(repo, conn):
    from src.alten_resolutions import VersionResolution
    document = conn.execute('SELECT document_id FROM logical_documents').fetchone()[0]
    versions = repo.get_document_versions(document)
    return VersionResolution(document, versions[0].version_id, 'Synthetic review',
                             tuple(v.version_id for v in versions))


def test_selection_replay_and_changed_decision_requires_rebuild(snapshot):
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)
    choice = resolution_for(repo, conn)
    finalize_alten(conn, result.run_id, bindings, sources, (choice,))
    before = CanonicalStateReader(conn).read(include_operational_metadata=True)
    finalize_alten(conn, result.run_id, bindings, sources, (choice,))
    assert CanonicalStateReader(conn).read(include_operational_metadata=True) == before
    for changed in [replace(choice, reason='Changed review'),
                    replace(choice, version_id=choice.expected_version_ids[1])]:
        with pytest.raises(ValueError, match='rebuild'):
            finalize_alten(conn, result.run_id, bindings, sources, (changed,))
        assert CanonicalStateReader(conn).read(include_operational_metadata=True) == before
    ext = conn.execute('SELECT extraction_id FROM extractions WHERE extractor_name=?', (NAME,)).fetchone()[0]
    facts = {f.fact_key: f for f in repo.get_extraction_facts(ext)}
    manifest = json.loads(facts['projection/manifest'].value.value)
    assert manifest['resolution']['resolutions'][0]['version_id'] == choice.version_id
    assert manifest['resolution']['resolutions'][0]['reason'] == choice.reason


@pytest.mark.parametrize('mutation', ['extra', 'different', 'duplicate'])
def test_inventory_variants_rollback(snapshot, mutation):
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)
    choice = resolution_for(repo, conn)
    if mutation == 'extra':
        choice = replace(choice, expected_version_ids=choice.expected_version_ids + ('other',))
    elif mutation == 'different':
        choice = replace(choice, expected_version_ids=(choice.version_id, 'other'))
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError):
        finalize_alten(conn, result.run_id, bindings, sources,
                       (choice, choice) if mutation == 'duplicate' else (choice,))
    assert CanonicalStateReader(conn).read() == before


@pytest.mark.parametrize('mutation', ['page', 'fingerprint', 'partial', 'old_revision'])
def test_inconsistent_selected_support(snapshot, mutation):
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)
    choice = resolution_for(repo, conn)
    if mutation in ('partial', 'old_revision'):
        finalize_alten(conn, result.run_id, bindings, sources, (choice,))
        if mutation == 'partial':
            conn.execute("DELETE FROM documentary_facts WHERE fact_key='projection/manifest'")
        else:
            conn.execute("UPDATE extractions SET extractor_revision='alten-economic-projection/v1' WHERE extractor_name=?", (NAME,))
    elif mutation == 'page':
        conn.execute('DELETE FROM fact_pages WHERE fact_id IN (SELECT f.fact_id FROM documentary_facts f JOIN extractions e USING(extraction_id) WHERE e.version_id=?)', (choice.version_id,))
    else:
        conn.execute('UPDATE extractions SET content_hash=? WHERE version_id=?', ('a'*64, choice.version_id))
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError):
        finalize_alten(conn, result.run_id, bindings, sources, (choice,))
    assert CanonicalStateReader(conn).read() == before


def test_builder_resolution_file_roundtrip_and_reproducibility(tmp_path, monkeypatch):
    import src.canonical_build as module
    from src.alten_resolutions import encode_resolutions
    from src.canonical_build import BuildConfig, CorpusBuild, build
    person = Person(person_id(), 'synthetic')
    corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'synthetic/v1')
    root = tmp_path/'inputs'
    root.mkdir()
    for n in range(2):
        (root/f'{n}.pdf').write_bytes(str(n).encode())
    monkeypatch.setattr(module, 'AltenProcessor', SyntheticAlten)
    config = BuildConfig(person, (CorpusBuild(corpus, root, 'alten', None, ()),), 'synthetic/v1')
    baseline = tmp_path/'baseline.sqlite'
    build(config, baseline)
    with open_database(baseline, mode='verify') as db:
        choice = resolution_for(RelationRepository(db.connection), db.connection)
    path = tmp_path/'resolutions.json'
    path.write_bytes(encode_resolutions((choice,)))
    config = replace(config, alten_resolutions=path)
    a, b = tmp_path/'a.sqlite', tmp_path/'b.sqlite'
    build(config, a)
    build(config, b)
    with open_database(a, mode='verify') as first, open_database(b, mode='verify') as second:
        assert CanonicalStateReader(first.connection).read() == CanonicalStateReader(second.connection).read()
        assert first.connection.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 2
    path.write_bytes(encode_resolutions((replace(choice, expected_version_ids=(choice.version_id,)),)))
    with pytest.raises(ValueError, match='inventory'):
        build(config, tmp_path/'failed.sqlite')
    assert not (tmp_path/'failed.sqlite').exists()
    assert not list(tmp_path.glob('.canonical-build-*'))


class TwoDocuments(SyntheticAlten):
    def prepare(self, data, filename):
        prepared = super().prepare(data, filename)
        # Every physical file supplies two logical periods, each with two versions.
        period = {k: v.replace('2025-01', '2025-03') if isinstance(v, str) else v
                  for k, v in prepared.periods[0].items()}
        version = {k: v.replace('2025-01', '2025-03') if isinstance(v, str) else v
                   for k, v in prepared.versions[0].items()}
        version['page_number'] = 2
        version['version_key'] = version['version_key'].replace(':page:1', ':page:2')
        return AltenPDF(2, prepared.periods + (period,), prepared.versions + (version,))


@pytest.mark.parametrize('case', ['incomplete', 'foreign_version', 'late_error'])
def test_two_document_atomic_validation(snapshot, case):
    from src.alten_resolutions import VersionResolution
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2, processor=TwoDocuments())
    documents = [d for (d,) in conn.execute('SELECT document_id FROM logical_documents ORDER BY document_id')]
    choices = []
    for doc in documents:
        versions = tuple(v.version_id for v in repo.get_document_versions(doc))
        choices.append(VersionResolution(doc, versions[0], 'Reviewed', versions))
    if case == 'incomplete':
        choices.pop()
    elif case == 'foreign_version':
        choices[1] = replace(choices[1], version_id=choices[0].version_id,
                             expected_version_ids=(choices[0].version_id,))
    else:
        conn.execute('UPDATE extractions SET content_hash=? WHERE version_id=?', ('a'*64, choices[1].version_id))
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError):
        finalize_alten(conn, result.run_id, bindings, sources, tuple(choices))
    assert CanonicalStateReader(conn).read() == before
    assert conn.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0


def test_resolution_cannot_cross_configured_corpus(snapshot):
    from src.alten_resolutions import VersionResolution
    from src.canonical.documents import DocumentVersion, LogicalDocument, document_id, version_id
    repo, conn, bindings, _ = snapshot
    result, sources, _ = prepare(snapshot, count=2)
    person = Person(person_id(), 'other')
    corpus = Corpus(corpus_id(), person.person_id, 'other', 'synthetic/v1')
    repo.register_person(person)
    repo.register_corpus(corpus)
    doc = LogicalDocument(document_id(corpus.corpus_id, 'other'), corpus.corpus_id, None, 'payroll', 'other')
    repo.register_document(doc)
    file_id = conn.execute('SELECT file_id FROM source_files LIMIT 1').fetchone()[0]
    version = DocumentVersion(version_id(doc.document_id, file_id, 'page:1'), doc.document_id, file_id, 'page:1')
    repo.register_version(version)
    choice = VersionResolution(doc.document_id, version.version_id, 'Reviewed', (version.version_id,))
    before = CanonicalStateReader(conn).read()
    with pytest.raises(ValueError, match='unknown document'):
        finalize_alten(conn, result.run_id, bindings, sources, (choice,))
    assert CanonicalStateReader(conn).read() == before
