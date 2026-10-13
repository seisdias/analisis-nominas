"""Read-only A.3 checks on explicitly prepared private builds; no salary oracle.

These checks validate provenance and selection, not independent payroll amounts.
Build both candidates with the current implementation before running this file.
"""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.alten_projection import NAME, finalize_alten
from src.alten_resolutions import decode_resolutions
from src.candidate_selection import select_candidates
from src.canonical import sha256_bytes
from src.canonical_build import load_config
from src.canonical_ingestion import CorpusInput, inventory
from src.persistence.relations import RelationRepository
from src.persistence.state import OPERATIONAL_COLUMNS, CanonicalStateReader

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / 'data/private'


@pytest.fixture
def artifacts():
    paths = [PRIVATE/name for name in (
        'canonical-candidate-a3-baseline.sqlite', 'canonical-candidate-a3-v2.sqlite',
        'canonical-candidate-a3-v2-repro.sqlite', 'canonical-build-a3-v1.json')]
    if not all(p.is_file() for p in paths):
        pytest.skip('Explicit private A.3 builds are required')
    return paths


def readonly(path):
    conn = sqlite3.connect(f'file:{path.resolve()}?mode=ro', uri=True)
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def test_private_selection_lineage_and_baseline_preserved(artifacts):
    baseline, candidate, _, config_path = artifacts
    config = load_config(config_path)
    assert config.alten_resolutions is not None
    choices = decode_resolutions(config.alten_resolutions.read_bytes())
    spec = next(s for s in config.corpora if s.processor_kind == 'alten')
    with readonly(baseline) as before, readonly(candidate) as after:
        assert after.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not after.execute('PRAGMA foreign_key_check').fetchall()
        assert after.execute('SELECT max(version) FROM schema_migrations').fetchone()[0] == 8
        repo = RelationRepository(after)
        documents = [d for (d,) in after.execute('SELECT document_id FROM logical_documents WHERE corpus_id=?', (spec.corpus.corpus_id,))]
        assert len(documents) == 55
        counts = [len(repo.get_document_versions(d)) for d in documents]
        assert counts.count(1) == 30 and sum(counts) == 82 and len(choices) == 25
        for table in ('logical_documents', 'document_versions', 'version_pages', 'source_files', 'file_locations'):
            columns = [r[1] for r in before.execute(f'PRAGMA table_info({table})')
                       if r[1] not in OPERATIONAL_COLUMNS[table]]
            sql = f'SELECT {",".join(columns)} FROM {table}'
            assert set(before.execute(sql)) == set(after.execute(sql))
        # Every original extraction and fact remains byte-for-byte semantically intact.
        for table, identity in [('extractions', 'extraction_id'), ('documentary_facts', 'fact_id')]:
            columns = [r[1] for r in before.execute(f'PRAGMA table_info({table})') if r[1] != 'created_at']
            condition = ("extractor_name != 'alten-economic-projection'" if table == 'extractions' else
                         "extraction_id IN (SELECT extraction_id FROM extractions WHERE extractor_name != 'alten-economic-projection')")
            for row in before.execute(f'SELECT {",".join(columns)} FROM {table} WHERE {condition}'):
                key = row[columns.index(identity)]
                assert after.execute(f'SELECT {",".join(columns)} FROM {table} WHERE {identity}=?', (key,)).fetchone() == row
        # A.2 single-version economic values are preserved despite v2 identities.
        economic = ('SELECT o.magnitude,o.coefficient,o.scale,o.currency,o.eligibility '
                    'FROM economic_observations o JOIN assessments USING(assessment_id) '
                    'WHERE document_id=? ORDER BY o.magnitude')
        for document in documents:
            if len(repo.get_document_versions(document)) == 1:
                assert before.execute(economic, (document,)).fetchall() == after.execute(economic, (document,)).fetchall()
        for choice in choices:
            assert choice.expected_version_ids == tuple(sorted(v.version_id for v in repo.get_document_versions(choice.document_id)))
            version = repo.get_version(choice.version_id)
            assert version is not None
            file = repo.get_source_file(version.file_id)
            assert file is not None
            locations = after.execute('SELECT relative_path FROM file_locations WHERE corpus_id=? AND file_id=?', (spec.corpus.corpus_id, version.file_id)).fetchall()
            assert locations
            for (relative,) in locations:
                assert sha256_bytes((spec.source/relative).read_bytes()) == file.sha256
            pages = repo.get_version_pages(choice.version_id)
            assert len(pages) == 1
            assert version.segment_key == f'sha256:{file.sha256}:page:{pages[0].page_number}'
            projections = after.execute('SELECT extraction_id,version_id FROM extractions JOIN document_versions USING(version_id) WHERE document_id=? AND extractor_name=?', (choice.document_id, NAME)).fetchall()
            assert len(projections) == 1 and projections[0][1] == choice.version_id
            facts = {f.fact_key: f for f in repo.get_extraction_facts(projections[0][0])}
            manifest_text = facts['projection/manifest'].value.value
            assert isinstance(manifest_text, str)
            manifest = json.loads(manifest_text)
            assert decode_resolutions(json.dumps(manifest['resolution']).encode()) == (choice,)
            for key, fact in facts.items():
                if key.startswith('nomina.'):
                    source_id = facts['projection/' + key.removeprefix('nomina.') + '/source_fact'].value.value
                    assert isinstance(source_id, str)
                    source = repo.get_fact(source_id)
                    assert source is not None and fact.value == source.value
                    assert [p.page_number for p in repo.get_fact_pages(fact.fact_id)] == [p.page_number for p in repo.get_fact_pages(source.fact_id)]
        observations = after.execute('SELECT o.observation_id,o.eligibility FROM economic_observations o JOIN assessments USING(assessment_id) JOIN logical_documents USING(document_id) WHERE corpus_id=?', (spec.corpus.corpus_id,)).fetchall()
        assert len(observations) == 110 and {r[1] for r in observations} == {'evidence_only'}
        assert not {r[0] for r in observations} & {e.observation.observation_id for e in select_candidates(repo).candidates}
        assert after.execute('SELECT count(*) FROM extractions e JOIN document_versions USING(version_id) JOIN logical_documents USING(document_id) WHERE corpus_id=? AND e.extractor_name=?', (spec.corpus.corpus_id, NAME)).fetchone()[0] == 55


def test_private_build_reproducibility(artifacts):
    _, candidate, repeat, _ = artifacts
    with readonly(candidate) as a, readonly(repeat) as b:
        assert CanonicalStateReader(a).read() == CanonicalStateReader(b).read()


def test_private_replay_is_idempotent_on_isolated_copy(artifacts, tmp_path):
    _, candidate, _, config_path = artifacts
    config = load_config(config_path)
    assert config.alten_resolutions is not None
    choices = decode_resolutions(config.alten_resolutions.read_bytes())
    bindings = tuple(CorpusInput(s.corpus.corpus_id, s.source, s.corpus.label) for s in config.corpora)
    sources = inventory(bindings)
    alten_ids = {s.corpus.corpus_id for s in config.corpora if s.processor_kind == 'alten'}
    copy = tmp_path/'replay.sqlite'
    shutil.copyfile(candidate, copy)
    with sqlite3.connect(copy) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        before = CanonicalStateReader(conn).read(include_operational_metadata=True)
        run = conn.execute('SELECT run_id FROM ingest_runs').fetchone()[0]
        finalize_alten(conn, run, tuple(b for b in bindings if b.corpus_id in alten_ids), sources, choices)
        assert CanonicalStateReader(conn).read(include_operational_metadata=True) == before
