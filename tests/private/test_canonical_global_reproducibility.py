"""Build A, replay A, build B: one global certification, no runtime database."""
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from src.candidate_selection import select_candidates
from src.canonical.decisions import encode_decisions
from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical_ingestion import CorpusInput, PDFProcessor, ingest, inventory
from src.ingestion_processors import AltenProcessor, OrdinaryProcessor
from src.manual_decisions import import_decisions
from src.parsers.parser_factory import ParserFactory
from src.persistence import open_database, verify_schema
from src.persistence.decisions import DecisionRepository
from src.persistence.state import CanonicalStateReader

ROOT = Path(__file__).resolve().parents[2]
NAMES = ('coritel', 'insis4', 'ineco', 'exceltic', 'altran', 'alten')
EXPECTED = {'coritel': {'processed': 17}, 'insis4': {'processed': 23, 'skipped': 2},
            'ineco': {'processed': 60, 'skipped': 1}, 'exceltic': {'processed': 8},
            'altran': {'processed': 73, 'skipped': 5}, 'alten': {'processed': 52, 'skipped': 3}}


EXPECTED_SOURCE_COUNTS = {
    'assessments': 259, 'corpora': 6, 'document_relations': 0, 'document_versions': 259,
    'documentary_facts': 36470, 'economic_observations': 362, 'employers': 0,
    'extractions': 259, 'fact_pages': 35969, 'file_locations': 244, 'ingest_items': 244,
    'ingest_runs': 1, 'logical_documents': 233, 'manual_decisions': 0,
    'observation_facts': 362, 'observation_relations': 0, 'persons': 1, 'rules': 2,
    'schema_migrations': 8, 'source_files': 242, 'version_pages': 260,
}
HISTORICAL_V7_FINGERPRINT = '9e12297442f73805abf7207144363d44b51c6d2c5c1e9b9b516e303d2797387f'


def test_global_two_builds_and_identical_replay(tmp_path):
    manifest_bytes = {name: (ROOT/'data/private'/f'{name}-manifest.json').read_bytes()
                      for name in NAMES if name != 'coritel'}
    manifests = {name: json.loads(data) for name, data in manifest_bytes.items()}
    decisions = encode_decisions(())  # No invented human decisions about real evidence.
    snapshots, strict_snapshots, alten_identities, classifications, plans = [], [], [], [], []
    for label in ('a', 'b'):
        # Independent parser instances, database, schema ledger and operational times.
        processors: dict[str, PDFProcessor] = {name: OrdinaryProcessor(ParserFactory().obtener_parser('insis' if name == 'insis4' else name))
                      for name in NAMES if name != 'alten'}
        processors['alten'] = AltenProcessor()
        with open_database(tmp_path/f'build-{label}.sqlite', mode='create',
                           application_revision='global-certification/v1') as db:
            repo = DecisionRepository(db.connection)
            person = Person(person_id(UUID(int=1)), 'private-certification')
            repo.register_person(person)
            bindings, corpora = [], {}
            for index, name in enumerate(NAMES, 2):
                corpus = Corpus(corpus_id(UUID(int=index)), person.person_id, name, 'certified-corpus/v1')
                repo.register_corpus(corpus)
                corpora[name] = corpus.corpus_id
                bindings.append(CorpusInput(corpus.corpus_id, ROOT/'data/test'/name, name))
            sources = inventory(bindings)
            assert len(sources) == 244
            certificates = {e['filename'] for e in manifests['altran']['certificates']}
            sources = tuple(replace(s, skip_reason='annual_certificate') if s.corpus_id == corpora['altran']
                            and s.relative_path in certificates else s for s in sources)
            for name, sections in {'ineco': ('textual', 'scanned'), 'exceltic': ('textual', 'scanned'),
                                   'altran': ('payrolls', 'certificates', 'scanned'), 'alten': ('physical_documents',)}.items():
                expected = {e['filename']: e['sha256_pdf'] for section in sections for e in manifests[name][section]}
                assert {s.relative_path: s.sha256 for s in sources if s.corpus_id == corpora[name]} == expected
            plans.append(sources)
            if label == 'b':
                bindings.reverse()
                sources = tuple(reversed(sources))
            result = ingest(repo, bindings, processors, sources=sources)
            assert (result.processed, result.skipped, result.failed) == (233, 11, 0)
            import_decisions(repo, decisions)
            counts = {name: dict(db.connection.execute(
                'SELECT status,count(*) FROM ingest_items WHERE corpus_id=? GROUP BY status',
                (corpora[name],)).fetchall()) for name in NAMES}
            assert counts == EXPECTED
            classifications.append(tuple(db.connection.execute(
                'SELECT corpus_id,relative_path,expected_sha256,status,reason_code FROM ingest_items ORDER BY corpus_id,relative_path')))
            assert db.connection.execute('SELECT count(DISTINCT corpus_id) FROM logical_documents').fetchone()[0] == 6
            for corpus_identity in corpora.values():
                assert db.connection.execute(
                    "SELECT count(*) FROM documentary_facts f JOIN extractions e USING(extraction_id) "
                    "JOIN document_versions v USING(version_id) JOIN logical_documents d USING(document_id) "
                    "WHERE d.corpus_id=? AND f.fact_key IN ('nomina.empresa','payload/empresa')", (corpus_identity,)
                ).fetchone()[0] > 0
            groups = tuple(r[0] for r in db.connection.execute(
                'SELECT document_id FROM logical_documents WHERE corpus_id=? ORDER BY document_id', (corpora['alten'],)))
            versions = tuple(r[0] for r in db.connection.execute(
                'SELECT version_id FROM document_versions JOIN logical_documents USING(document_id) WHERE corpus_id=? ORDER BY version_id', (corpora['alten'],)))
            assert len(groups) == 52 and len(versions) == 78
            alten_identities.append((groups, versions))
            assert not select_candidates(repo).candidates
            assert db.connection.execute(
                'SELECT count(*) FROM economic_observations JOIN assessments USING(assessment_id) '
                'JOIN logical_documents USING(document_id) WHERE corpus_id=?', (corpora['alten'],)
            ).fetchone()[0] == 0
            assert {r[0] for r in db.connection.execute(
                'SELECT status FROM assessments JOIN logical_documents USING(document_id) WHERE corpus_id=?', (corpora['alten'],))} <= {'pending', 'ambiguous'}
            assert db.connection.execute(
                'SELECT count(*) FROM documentary_facts f LEFT JOIN extractions e USING(extraction_id) '
                'LEFT JOIN document_versions v USING(version_id) LEFT JOIN source_files s USING(file_id) '
                'WHERE s.file_id IS NULL').fetchone()[0] == 0
            assert db.connection.execute(
                'SELECT count(*) FROM observation_facts l LEFT JOIN documentary_facts f USING(fact_id) WHERE f.fact_id IS NULL'
            ).fetchone()[0] == 0
            assert verify_schema(db.connection).current_version == 8
            assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
            reader = CanonicalStateReader(db.connection)
            snapshots.append(reader.read())
            assert dict(snapshots[-1].table_counts) == EXPECTED_SOURCE_COUNTS
            assert b'canonical-persisted-state/v2' in snapshots[-1].canonical_content
            assert snapshots[-1].fingerprint != HISTORICAL_V7_FINGERPRINT
            audit = reader.read(include_derived_cache=True)
            assert dict(audit.table_counts) == {**EXPECTED_SOURCE_COUNTS, 'derived_results': 0, 'derived_inputs': 0}
            assert audit.fingerprint != snapshots[-1].fingerprint
            strict_snapshots.append(reader.read(include_operational_metadata=True))
            if label == 'a':
                assert ingest(repo, list(reversed(bindings)), processors, sources=tuple(reversed(sources))) == result
                import_decisions(repo, decisions)
                assert reader.read() == snapshots[-1]
                assert reader.read(include_operational_metadata=True) == strict_snapshots[-1]
                assert db.connection.execute('SELECT count(*) FROM ingest_runs').fetchone()[0] == 1
    assert plans[0] == plans[1]
    assert snapshots[0] == snapshots[1]  # Exact canonical bytes and all table counts, not only SHA256.
    assert strict_snapshots[0].fingerprint != strict_snapshots[1].fingerprint
    assert alten_identities[0] == alten_identities[1]
    assert classifications[0] == classifications[1]
    for name, original in manifest_bytes.items():
        assert (ROOT/'data/private'/f'{name}-manifest.json').read_bytes() == original
    print('Global logical fingerprint:', snapshots[0].fingerprint)
    print('Canonical table counts:', dict(snapshots[0].table_counts))
    print('Build A = replay A = build B; 244 PDFs / 233 processed / 11 skipped / 0 failed; ALTEN 52/78/0')
