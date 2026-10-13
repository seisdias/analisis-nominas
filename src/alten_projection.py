"""ALTEN vocabulary projection for a closed, fully ingested build snapshot.

Only the fresh builder calls this finalization step. Incremental ingestion stays
purely documentary: a prefix of a corpus cannot establish version uniqueness.
Source facts are immutable; new identities bind the projection to their exact
fingerprints and physical pages. No totals, context or currency are inferred.
"""
import json
import sqlite3
from importlib.resources import files

from src.alten_canonical import REVISION as SOURCE_REVISION
from src.alten_resolutions import VersionResolution, encode_resolutions
from src.canonical import CanonicalValue, ValueState, canonical_sha256, sha256_bytes
from src.canonical.documents import Extraction, extraction_id
from src.canonical.economics import fact_fingerprint
from src.canonical.evidence import utc_now
from src.canonical.facts import DocumentaryFact, FactDraft, FactPage
from src.canonical_ingestion import CorpusInput, InputPDF, inventory
from src.economic_mapping import evaluate_direct_totals
from src.persistence.relations import RelationRepository

REVISION = 'alten-economic-projection/v2'
NAME = 'alten-economic-projection'
# Direct aliases only. Context is also copied so every extraction agrees in the
# inspector. Deductions/concepts remain documentary and are not reconstructed.
FIELDS = ('total_devengado', 'liquido_percibir', 'empresa', 'cif', 'anio', 'mes',
          'fecha_inicio', 'fecha_fin', 'tipo')


def finalize_alten(connection: sqlite3.Connection, run_id: str,
                   bindings: tuple[CorpusInput, ...], sources: tuple[InputPDF, ...],
                   resolutions: tuple[VersionResolution, ...] = ()) -> None:
    """Finalize a fresh build, never an arbitrary partial/incremental database.

    All configured ALTEN roots must still match their initial full inventory.
    Explicit omissions and unextractable PDFs cannot establish completeness.
    Only certificates recognized by the existing processor may be skipped.
    Replaying the same closed snapshot is idempotent.
    """
    if not bindings:
        if resolutions:
            raise ValueError('ALTEN resolutions require a configured corpus')
        return
    if len({r.document_id for r in resolutions}) != len(resolutions):
        raise ValueError('Multiple ALTEN resolutions for one document')
    corpus_ids = {b.corpus_id for b in bindings}
    selected = tuple(s for s in sources if s.corpus_id in corpus_ids)
    if any(s.skip_reason is not None for s in selected) or inventory(bindings) != selected:
        raise ValueError('ALTEN projection requires an unchanged complete inventory without exclusions')
    repo = RelationRepository(connection)
    with repo.transaction():
        runs = connection.execute('SELECT run_id,status FROM ingest_runs').fetchall()
        if runs != [(run_id, 'complete')]:
            raise ValueError('ALTEN projection requires one complete fresh-build ingestion run')
        known_documents = {
            document_id
            for (document_id,) in connection.execute(
                'SELECT document_id FROM logical_documents WHERE corpus_id IN ('
                + ','.join('?' for _ in corpus_ids) + ')',
                tuple(sorted(corpus_ids)),
            )
        }
        if any(r.document_id not in known_documents for r in resolutions):
            raise ValueError('ALTEN resolution references an unknown document')
        if resolutions:
            multiversion = {d for d in known_documents if len(repo.get_document_versions(d)) > 1}
            if multiversion - {r.document_id for r in resolutions}:
                raise ValueError('ALTEN resolutions are incomplete for the multiversion inventory')
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
                for candidate in versions:
                    file = repo.get_source_file(candidate.file_id)
                    pages = repo.get_version_pages(candidate.version_id)
                    if (file is None or len(pages) != 1
                            or candidate.segment_key != f'sha256:{file.sha256}:page:{pages[0].page_number}'
                            or not any(s.sha256 == file.sha256 and s.corpus_id == corpus for s in selected)):
                        raise ValueError('ALTEN source documentary identity is inconsistent')
                choices = [r for r in resolutions if r.document_id == identity]
                if len(versions) != 1 and not choices:
                    if connection.execute('SELECT 1 FROM economic_observations o JOIN assessments a '
                                          'USING(assessment_id) WHERE a.document_id=?', (identity,)).fetchone():
                        raise ValueError('Multiversion ALTEN document already has observations; rebuild required')
                    continue
                if choices:
                    matches = [v for v in versions if v.version_id == choices[0].version_id]
                    if len(matches) != 1:
                        raise ValueError('ALTEN resolution references an unavailable version')
                    if choices[0].expected_version_ids != tuple(sorted(v.version_id for v in versions)):
                        raise ValueError('ALTEN resolution has a stale version inventory')
                    version = matches[0]
                else:
                    version = versions[0]
                rows = connection.execute('SELECT extraction_id,extractor_name,extractor_revision '
                                          'FROM extractions WHERE version_id=?', (version.version_id,)).fetchall()
                original = [r[0] for r in rows if r[1:] == ('alten-legacy-evidence', SOURCE_REVISION)]
                if len(original) != 1 or any(r[1:] not in (('alten-legacy-evidence', SOURCE_REVISION), (NAME, REVISION)) for r in rows):
                    raise ValueError('ALTEN source extraction is not unique or supported')
                _project(connection, repo, identity, original[0], run_id, choices[0] if choices else None)


def _project(connection: sqlite3.Connection, repo: RelationRepository, document_id: str, source_id: str, run_id: str,
             resolution: VersionResolution | None) -> None:
    source = repo.get_extraction(source_id)
    assert source is not None
    originals = repo.get_extraction_facts(source_id)
    if source.content_hash != canonical_sha256({f.fact_key: f.value for f in originals}):
        raise ValueError('ALTEN source content fingerprint mismatch')
    by_key = {f.fact_key: f for f in originals}
    version = repo.get_version(source.version_id)
    assert version is not None
    file = repo.get_source_file(version.file_id)
    assert file is not None
    pages = [p.page_number for p in repo.get_version_pages(version.version_id)]
    if (by_key.get('legacy/pdf_sha256') is None
            or by_key['legacy/pdf_sha256'].value.value != file.sha256
            or by_key.get('legacy/version_key') is None
            or by_key['legacy/version_key'].value.value != version.segment_key
            or any([p.page_number for p in repo.get_fact_pages(f.fact_id)] != pages
                   for f in originals if f.fact_key.startswith('payload/'))):
        raise ValueError('ALTEN source documentary support is inconsistent')
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
        'source_content_hash': source.content_hash, 'ingest_run': str(run_id), 'sources': provenance,
        'resolution': json.loads(encode_resolutions((resolution,))) if resolution else None}
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
    drafts.append(FactDraft('projection/manifest', CanonicalValue(state=ValueState.PRESENT,
        value=json.dumps(manifest, sort_keys=True, separators=(',', ':')))))
    expected_id = extraction_id(source.version_id, NAME, REVISION, config)
    existing = connection.execute(
        'SELECT e.extraction_id FROM extractions e JOIN document_versions v USING(version_id) '
        'WHERE v.document_id=? AND e.extractor_name=?', (document_id, NAME)).fetchall()
    if not existing and connection.execute(
            'SELECT 1 FROM economic_observations JOIN assessments USING(assessment_id) '
            'WHERE document_id=?', (document_id,)).fetchone():
        raise ValueError('ALTEN observations without projection; fresh rebuild required')
    if existing and existing != [(expected_id,)]:
        raise ValueError('ALTEN projection changed or partial; fresh rebuild required')
    if existing:
        stored = repo.get_extraction_facts(expected_id)
        if canonical_sha256({f.fact_key: f.value for f in stored}) != canonical_sha256(
                {d.fact_key: d.value for d in drafts}):
            raise ValueError('ALTEN projection is partial; fresh rebuild required')
        for fact in stored:
            if fact.fact_key.startswith('nomina.'):
                original = by_key['payload/' + fact.fact_key.removeprefix('nomina.')]
                if [p.page_number for p in repo.get_fact_pages(fact.fact_id)] != [
                        p.page_number for p in repo.get_fact_pages(original.fact_id)]:
                    raise ValueError('ALTEN projection pages are partial; fresh rebuild required')
        interpretation = evaluate_direct_totals(document_id, stored)
        if (repo.get_assessment(interpretation.assessment.assessment_id) is None
                or any(repo.get_observation(e.observation.observation_id) is None
                       for e in interpretation.observations)):
            raise ValueError('ALTEN projection observations are partial; fresh rebuild required')
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
