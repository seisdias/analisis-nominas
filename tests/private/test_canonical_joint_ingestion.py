"""One joint temporary SQLite certification, without legacy database writes."""
import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from src.candidate_selection import select_candidates
from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical_ingestion import CorpusInput, ingest, inventory
from src.ingestion_processors import AltenProcessor, OrdinaryProcessor
from src.parsers.parser_factory import ParserFactory
from src.persistence import open_database, verify_schema
from src.persistence.relations import RelationRepository

ROOT = Path(__file__).resolve().parents[2]


def test_joint_six_companies_in_one_canonical_database(tmp_path):
    names = ('coritel', 'insis4', 'ineco', 'exceltic', 'altran', 'alten')
    processors = {name: OrdinaryProcessor(ParserFactory().obtener_parser('insis' if name == 'insis4' else name))
                  for name in names if name != 'alten'}
    processors['alten'] = AltenProcessor()
    manifests = {name: json.loads((ROOT/'data/private'/f'{name}-manifest.json').read_text())
                 for name in names if name != 'coritel'}
    before_manifests = {name: (ROOT/'data/private'/f'{name}-manifest.json').read_bytes() for name in manifests}
    with open_database(tmp_path/'joint.sqlite', mode='create') as db:
        repo = RelationRepository(db.connection)
        person = Person(person_id(UUID(int=1)), 'private-certification')
        repo.register_person(person)
        bindings = []
        corpora = {}
        for index, name in enumerate(names, 2):
            corpus = Corpus(corpus_id(UUID(int=index)), person.person_id, name, 'certified-corpus/v1')
            repo.register_corpus(corpus)
            corpora[name] = corpus.corpus_id
            bindings.append(CorpusInput(corpus.corpus_id, ROOT/'data/test'/name, name))
        sources = inventory(bindings)
        assert len(sources) == 244
        by_name = {b.corpus_id: b.processor_id for b in bindings}
        # Explicit certified non-payroll scope. No filename heuristic in the core.
        certificates = {e['filename'] for e in manifests['altran']['certificates']}
        sources = tuple(replace(s, skip_reason='annual_certificate') if by_name[s.corpus_id] == 'altran'
                        and s.relative_path in certificates else s for s in sources)
        for name, sections in {'ineco': ('textual', 'scanned'), 'exceltic': ('textual', 'scanned'),
                               'altran': ('payrolls', 'certificates', 'scanned'), 'alten': ('physical_documents',)}.items():
            expected = {e['filename']: e['sha256_pdf'] for section in sections for e in manifests[name][section]}
            assert {s.relative_path: s.sha256 for s in sources if s.corpus_id == corpora[name]} == expected
        result = ingest(repo, bindings, processors, sources=sources)
        counts = {name: dict(db.connection.execute('SELECT status,count(*) FROM ingest_items WHERE corpus_id=? GROUP BY status',
                                                  (corpora[name],)).fetchall()) for name in names}
        print('Joint canonical certification:', result, counts)
        assert result.failed == 0, counts
        assert (result.processed, result.skipped) == (233, 11)
        assert counts == {'coritel': {'processed': 17}, 'insis4': {'processed': 23, 'skipped': 2},
                          'ineco': {'processed': 60, 'skipped': 1}, 'exceltic': {'processed': 8},
                          'altran': {'processed': 73, 'skipped': 5}, 'alten': {'processed': 52, 'skipped': 3}}
        assert db.connection.execute('SELECT count(DISTINCT corpus_id) FROM logical_documents').fetchone()[0] == 6
        for corpus in corpora.values():
            assert db.connection.execute(
                "SELECT count(*) FROM documentary_facts f JOIN extractions e USING(extraction_id) "
                "JOIN document_versions v USING(version_id) JOIN logical_documents d USING(document_id) "
                "WHERE d.corpus_id=? AND f.fact_key IN ('nomina.empresa','payload/empresa')", (corpus,)
            ).fetchone()[0] > 0
        alten = corpora['alten']
        assert db.connection.execute('SELECT count(*) FROM logical_documents WHERE corpus_id=?', (alten,)).fetchone()[0] == 52
        assert db.connection.execute('SELECT count(*) FROM document_versions v JOIN logical_documents d USING(document_id) WHERE d.corpus_id=?', (alten,)).fetchone()[0] == 78
        assert db.connection.execute('SELECT count(*) FROM economic_observations o JOIN assessments a USING(assessment_id) JOIN logical_documents d USING(document_id) WHERE d.corpus_id=?', (alten,)).fetchone()[0] == 0
        assert not select_candidates(repo).candidates  # Certified direct totals remain evidence_only.
        assert db.connection.execute('SELECT count(*) FROM documentary_facts f LEFT JOIN extractions e USING(extraction_id) LEFT JOIN document_versions v USING(version_id) LEFT JOIN source_files s USING(file_id) WHERE s.file_id IS NULL').fetchone()[0] == 0
        assert {r[0] for r in db.connection.execute('SELECT status FROM assessments a JOIN logical_documents d USING(document_id) WHERE d.corpus_id=?', (alten,))} <= {'pending', 'ambiguous'}
        assert verify_schema(db.connection).current_version == 7
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
        before = tuple(db.connection.iterdump())
        assert ingest(repo, list(reversed(bindings)), processors, sources=tuple(reversed(sources))) == result
        assert tuple(db.connection.iterdump()) == before
    for name, data in before_manifests.items():
        assert (ROOT/'data/private'/f'{name}-manifest.json').read_bytes() == data
