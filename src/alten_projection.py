"""ALTEN vocabulary projection for a closed, fully ingested build snapshot.

Only the fresh builder calls this finalization step. Incremental ingestion stays
purely documentary: a prefix of a corpus cannot establish version uniqueness.
Source facts are immutable; new identities bind the projection to their exact
fingerprints and physical pages. No totals, context or currency are inferred.
"""
import sqlite3
from importlib.resources import files

from src.alten_canonical import REVISION as SOURCE_REVISION
from src.canonical import CanonicalValue, ValueState, canonical_sha256, sha256_bytes
from src.canonical.documents import Extraction, extraction_id
from src.canonical.economics import fact_fingerprint
from src.canonical.evidence import utc_now
from src.canonical.facts import DocumentaryFact, FactDraft, FactPage
from src.canonical_ingestion import CorpusInput, InputPDF, inventory
from src.economic_mapping import evaluate_direct_totals
from src.persistence.relations import RelationRepository

REVISION = 'alten-economic-projection/v1'
NAME = 'alten-economic-projection'
# Direct aliases only. Context is also copied so every extraction agrees in the
# inspector. Deductions/concepts remain documentary and are not reconstructed.
FIELDS = ('total_devengado', 'liquido_percibir', 'empresa', 'cif', 'anio', 'mes',
          'fecha_inicio', 'fecha_fin', 'tipo')


def finalize_alten(connection: sqlite3.Connection, run_id: str,
                   bindings: tuple[CorpusInput, ...], sources: tuple[InputPDF, ...]) -> None:
    """Finalize a fresh build, never an arbitrary partial/incremental database.

    All configured ALTEN roots must still match their initial full inventory.
    Explicit omissions and unextractable PDFs cannot establish completeness.
    Only certificates recognized by the existing processor may be skipped.
    Replaying the same closed snapshot is idempotent.
    """
    if not bindings:
        return
    corpus_ids = {b.corpus_id for b in bindings}
    selected = tuple(s for s in sources if s.corpus_id in corpus_ids)
    if any(s.skip_reason is not None for s in selected) or inventory(bindings) != selected:
        raise ValueError('ALTEN projection requires an unchanged complete inventory without exclusions')
    repo = RelationRepository(connection)
    with repo.transaction():
        runs = connection.execute('SELECT run_id,status FROM ingest_runs').fetchall()
        if runs != [(run_id, 'complete')]:
            raise ValueError('ALTEN projection requires one complete fresh-build ingestion run')
        for corpus in sorted(corpus_ids):
            expected = {(s.relative_path, s.sha256) for s in selected if s.corpus_id == corpus}
            rows = connection.execute('SELECT relative_path,expected_sha256,status,reason_code '
                                      'FROM ingest_items WHERE run_id=? AND corpus_id=?',
                                      (run_id, corpus)).fetchall()
            if not expected or {(r[0], r[1]) for r in rows} != expected or any(
                status != 'processed' and (status, reason) != ('skipped', 'annual_certificate')
                for _, _, status, reason in rows
            ):
                raise ValueError('ALTEN inventory has unprocessed or unclassified sources')
            # No source/version outside the completed run may be silently selected.
            uncovered = connection.execute(
                'SELECT 1 FROM document_versions v JOIN logical_documents d USING(document_id) '
                'WHERE d.corpus_id=? AND NOT EXISTS (SELECT 1 FROM ingest_items i '
                "WHERE i.run_id=? AND i.corpus_id=d.corpus_id AND i.file_id=v.file_id AND i.status='processed')",
                (corpus, run_id)).fetchone()
            if uncovered:
                raise ValueError('ALTEN versions are outside the completed inventory')
            documents = connection.execute('SELECT document_id FROM logical_documents WHERE corpus_id=? '
                                           'ORDER BY document_id', (corpus,)).fetchall()
            for (identity,) in documents:
                versions = repo.get_document_versions(identity)
                if len(versions) != 1:
                    if connection.execute('SELECT 1 FROM economic_observations o JOIN assessments a '
                                          'USING(assessment_id) WHERE a.document_id=?', (identity,)).fetchone():
                        raise ValueError('Multiversion ALTEN document already has observations; rebuild required')
                    continue
                version = versions[0]
                rows = connection.execute('SELECT extraction_id,extractor_name,extractor_revision '
                                          'FROM extractions WHERE version_id=?', (version.version_id,)).fetchall()
                original = [r[0] for r in rows if r[1:] == ('alten-legacy-evidence', SOURCE_REVISION)]
                if len(original) != 1 or any(r[1:] not in (('alten-legacy-evidence', SOURCE_REVISION), (NAME, REVISION)) for r in rows):
                    raise ValueError('ALTEN source extraction is not unique or supported')
                _project(repo, identity, original[0], run_id)


def _project(repo: RelationRepository, document_id: str, source_id: str, run_id: str) -> None:
    source = repo.get_extraction(source_id)
    assert source is not None
    originals = repo.get_extraction_facts(source_id)
    if source.content_hash != canonical_sha256({f.fact_key: f.value for f in originals}):
        raise ValueError('ALTEN source content fingerprint mismatch')
    by_key = {f.fact_key: f for f in originals}
    unresolved = by_key.get('legacy/resolution_status')
    if unresolved is None or unresolved.value.state != ValueState.PRESENT or unresolved.value.value != 'UNRESOLVED':
        raise ValueError('Only unresolved ALTEN source evidence is supported')
    selected = [by_key['payload/' + field] for field in FIELDS if 'payload/' + field in by_key]
    provenance = {f.fact_key: {'fact_id': str(f.fact_id), 'fingerprint': fact_fingerprint(f),
                              'pages': [p.page_number for p in repo.get_fact_pages(f.fact_id)]}
                  for f in originals}
    if any(not repo.get_fact_pages(f.fact_id) for f in selected):
        raise ValueError('ALTEN projected facts require physical page support')
    manifest = {'contract': REVISION, 'implementation': sha256_bytes(files('src').joinpath(
        'alten_projection.py').read_bytes()), 'source_extraction': str(source_id),
        'source_content_hash': source.content_hash, 'ingest_run': str(run_id), 'sources': provenance}
    config = canonical_sha256(manifest)
    drafts = [FactDraft('nomina.' + f.fact_key.removeprefix('payload/'), f.value) for f in selected]
    # Store the recoverable source references, not just an opaque manifest hash.
    for key, value in (('revision', REVISION), ('source_extraction', source_id),
                       ('source_content_hash', source.content_hash), ('ingest_run', run_id)):
        drafts.append(FactDraft('projection/' + key, CanonicalValue(state=ValueState.PRESENT, value=str(value))))
    for fact in selected:
        field = fact.fact_key.removeprefix('payload/')
        for key, value in (('source_fact', str(fact.fact_id)), ('fingerprint', fact_fingerprint(fact))):
            drafts.append(FactDraft(f'projection/{field}/{key}', CanonicalValue(state=ValueState.PRESENT, value=value)))
    stamp = utc_now()
    extraction = Extraction(extraction_id(source.version_id, NAME, REVISION, config), source.version_id,
                            NAME, REVISION, config, canonical_sha256({d.fact_key: d.value for d in drafts}), stamp)
    repo.register_extraction(extraction)
    facts = tuple(DocumentaryFact.from_draft(extraction.extraction_id, d, created_at=stamp) for d in drafts)
    for fact in facts:
        repo.register_fact(fact)
        if fact.fact_key.startswith('nomina.'):
            original = by_key['payload/' + fact.fact_key.removeprefix('nomina.')]
            for page in repo.get_fact_pages(original.fact_id):
                repo.associate_fact_page(FactPage(fact.fact_id, page.page_number))
    interpretation = evaluate_direct_totals(document_id, facts, created_at=stamp)
    repo.register_rule(interpretation.rule)
    repo.register_assessment(interpretation.assessment)
    for evidence in interpretation.observations:
        repo.register_observation(evidence.observation, evidence.fact_ids)
