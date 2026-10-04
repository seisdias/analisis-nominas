"""One directed certification of the legacy ALTEN → canonical evidence bridge."""
import json
from collections import Counter

from scripts.ingest_alten import run_ingestion
from src.alten_canonical import integrate_alten
from src.candidate_selection import select_candidates
from src.canonical import sha256_bytes
from src.canonical.evidence import (
    Corpus,
    FileLocation,
    Person,
    SourceFile,
    corpus_id,
    person_id,
    source_file_id,
)
from src.persistence import load_migrations as packaged_migrations
from src.persistence import open_database as packaged_open_database
from src.persistence import verify_schema as packaged_verify_schema
from src.persistence.relations import RelationRepository
from src.services.database_service import DatabaseService
from tests.private.test_alten_parser import CORPUS, MANIFEST


# Retain the certified v6 catalog and assertions as later migrations are added.
def load_migrations():
    return packaged_migrations()[:6]


def open_database(path, **kwargs):
    kwargs.setdefault('migrations', load_migrations())
    return packaged_open_database(path, **kwargs)


def verify_schema(connection):
    return packaged_verify_schema(connection, load_migrations())


def test_certified_alten_52_groups_78_versions_zero_candidates(tmp_path):
    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    legacy_path = str(tmp_path / 'legacy.sqlite')
    result = run_ingestion(CORPUS, legacy_path)
    assert (result.periods, result.versions, result.failed) == (52, 78, 0)
    legacy = DatabaseService(legacy_path)
    periods = legacy.obtener_periodos_documentales()
    versions = legacy.obtener_versiones_documentales()
    expected = {entry['version_key']: entry for entry in manifest['payroll_versions']}
    assert {v['version_key'] for v in versions} == set(expected)
    physical = {entry['sha256_pdf']: entry for entry in manifest['physical_documents']}
    with open_database(tmp_path / 'canonical.sqlite', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(), 'private-certification')
        corpus = Corpus(corpus_id(), person.person_id, 'ALTEN certified', 'alten-manifest/v1')
        repo.register_person(person)
        repo.register_corpus(corpus)
        inventory = []
        for digest in sorted({v['pdf_sha256'] for v in versions}):
            entry = physical[digest]
            data = (CORPUS / entry['filename']).read_bytes()
            assert sha256_bytes(data) == digest
            file = SourceFile(source_file_id(digest), digest, len(data), 'application/pdf', entry['paginas'])
            location = FileLocation(corpus.corpus_id, entry['filename'], file.file_id, entry['filename'])
            inventory.append((file, location))
        first = integrate_alten(repo, corpus.corpus_id, periods, versions, inventory)
        assert len(first.document_ids) == 52
        assert len(first.version_ids) == len(first.extraction_ids) == 78
        assert len(first.assessment_ids) == 52
        assert not select_candidates(repo).candidates
        assert db.connection.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 0
        assert Counter(a.status for a in repo.list_assessments()) == {'pending': 27, 'ambiguous': 25}
        by_key = {v['version_key']: v for v in versions}
        for identity in first.version_ids:
            version = repo.get_version(identity)
            assert version is not None
            original = by_key[version.segment_key]
            oracle = expected[version.segment_key]
            assert (original['period_key'], original['pdf_sha256'], original['page_number']) == (
                oracle['period_key'], oracle['sha256_pdf'], oracle['pagina'])
            assert version.file_id == source_file_id(original['pdf_sha256'])
            assert [p.page_number for p in repo.get_version_pages(identity)] == [oracle['pagina']]
        for identity in first.extraction_ids:
            extraction = repo.get_extraction(identity)
            assert extraction is not None
            version = repo.get_version(extraction.version_id)
            assert version is not None
            facts = {f.fact_key: f for f in repo.get_extraction_facts(identity)}
            assert facts['legacy/payload'].value.value == by_key[version.segment_key]['payload']
            assert facts['legacy/resolution_status'].value.value == 'UNRESOLVED'
            assert 'payload/total_devengado' in facts
            assert all(repo.get_fact_pages(f.fact_id) for k, f in facts.items() if k.startswith('payload/'))
        before = tuple(db.connection.iterdump())
        assert integrate_alten(repo, corpus.corpus_id, periods, versions, inventory,
                               created_at='2030-01-01T00:00:00Z') == first
        assert tuple(db.connection.iterdump()) == before
        assert not select_candidates(repo).candidates
        assert verify_schema(db.connection).current_version == 6
    assert legacy.obtener_todos() == []
    assert MANIFEST.read_bytes() == manifest_bytes
