"""Import legacy ALTEN documentary rows, never resolve or interpret payrolls.

The caller supplies a verified physical inventory (sizes cannot be recovered from
legacy rows). No PDF IO or parser execution occurs here. Extraction revision is
this bridge's revision, NOT an invented revision of the original parser.

Payload keys use escaped JSON Pointer paths. Repeated concepts retain their
persisted list position: the legacy payload has no unique concept-row identity.
Exact raw JSON is also retained, including numeric spelling and empty containers.
Numeric leaves preserve the legacy decimal spelling, not claimed PDF precision.
Unrepresentable decimals remain unreliable text candidates; nothing is rounded.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import Any

from src.canonical import CanonicalValue, ExactDecimal, ValueState, canonical_sha256, sha256_bytes
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    VersionPage,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import Assessment, Rule
from src.canonical.evidence import FileLocation, SourceFile, utc_now
from src.canonical.facts import DocumentaryFact, FactDraft, FactPage
from src.persistence.economics import EconomicRepository

REVISION = 'alten-legacy-evidence/v1'
_RESOLUTION_FIELDS = ('resolution_kind', 'selected_version_key', 'economic_payload',
                      'resolution_note', 'resolution_evidence', 'resolved_at')


@dataclass(frozen=True)
class AltenEvidenceResult:
    document_ids: tuple[str, ...]
    version_ids: tuple[str, ...]
    extraction_ids: tuple[str, ...]
    assessment_ids: tuple[str, ...]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate legacy JSON key')
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError('Non-finite legacy number')


def _leaves(value: Any, path: str = 'payload') -> Iterator[FactDraft]:
    if isinstance(value, dict):
        for key in sorted(value):
            escaped = key.replace('~', '~0').replace('/', '~1')
            yield from _leaves(value[key], path + '/' + escaped)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, path + '/' + str(index))
        return
    if value is None:
        canonical = CanonicalValue(state=ValueState.UNKNOWN, reason_code='legacy.absence_unspecified')
    elif isinstance(value, Decimal):
        try:
            exact = ExactDecimal.from_decimal(value)
        except (ValueError, OverflowError):
            canonical = CanonicalValue(state=ValueState.UNRELIABLE, value=str(value),
                                       reason_code='legacy.precision_not_representable')
        else:
            canonical = CanonicalValue(state=ValueState.UNRELIABLE if value == 0 else ValueState.PRESENT,
                                       value=exact, reason_code='legacy.zero_origin_unknown' if value == 0
                                       else 'legacy.normalized_value')
    else:
        canonical = CanonicalValue(state=ValueState.PRESENT,
                                   value=('true' if value else 'false') if type(value) is bool else value,
                                   reason_code='legacy.normalized_value')
    yield FactDraft(path, canonical)


def _text_fact(key: str, value: str) -> FactDraft:
    return FactDraft(key, CanonicalValue(state=ValueState.PRESENT, value=value))


def integrate_alten(
    repository: EconomicRepository, corpus_id: str,
    periods: Sequence[Mapping[str, Any]], versions: Sequence[Mapping[str, Any]],
    inventory: Sequence[tuple[SourceFile, FileLocation]], *, created_at: str | None = None,
) -> AltenEvidenceResult:
    """Atomically transfer an unresolved snapshot into an existing explicit corpus.

    Employer association stays unknown: documentary CIF is retained without
    inferring an employer entity. Metadata facts have no fabricated PDF page.
    No observations are generated, even for single-version unresolved groups.
    """
    stamp = utc_now() if created_at is None else created_at
    period_map = {p['period_key']: p for p in periods}
    if len(period_map) != len(periods) or len({v['version_key'] for v in versions}) != len(versions):
        raise ValueError('Repeated legacy identity in snapshot')
    if set(period_map) != {v['period_key'] for v in versions}:
        raise ValueError('Every group requires versions and every version requires a group')
    sources = {file.sha256: file for file, _ in inventory}
    for file, location in inventory:
        if location.corpus_id != corpus_id or location.file_id != file.file_id:
            raise ValueError('Inventory belongs to another corpus/file')
    rule = Rule.define('documentary', 'alten-unresolved', '1',
                       sha256_bytes(files('src').joinpath('alten_canonical.py').read_bytes()), created_at=stamp)
    config = canonical_sha256({'contract': REVISION})
    documents, version_ids, extraction_ids, assessments = [], [], [], []
    with repository.transaction():
        repository.register_rule(rule)
        for file, location in sorted(inventory, key=lambda pair: (pair[0].file_id, pair[1].relative_path)):
            repository.register_source_file(file)
            repository.register_location(location)
        for key, period in sorted(period_map.items()):
            if period['resolution_status'] != 'UNRESOLVED' or any(period.get(k) is not None for k in _RESOLUTION_FIELDS):
                raise ValueError('Only wholly unresolved ALTEN groups are supported')
            fields = ('cif', 'fecha_inicio', 'fecha_fin', 'tipo')
            if key != '|'.join(period[k] for k in fields):
                raise ValueError('Legacy period identity mismatch')
            doc = LogicalDocument(document_id(corpus_id, 'alten:' + key), corpus_id, None,
                                  period['tipo'], 'alten:' + key, stamp)
            repository.register_document(doc)
            documents.append(doc.document_id)
            facts = []
            group = sorted((v for v in versions if v['period_key'] == key), key=lambda v: v['version_key'])
            for row in group:
                digest, page = row['pdf_sha256'], row['page_number']
                if row['version_key'] != f'sha256:{digest}:page:{page}' or digest not in sources:
                    raise ValueError('Legacy version identity/inventory mismatch')
                payload = json.loads(row['payload'], parse_float=Decimal, parse_int=Decimal,
                                     parse_constant=_constant, object_pairs_hook=_object)
                if not isinstance(payload, dict) or any(payload.get(k) != period[k] for k in fields):
                    raise ValueError('Legacy payload differs from period identity')
                file = sources[digest]
                segment = row['version_key']
                version = DocumentVersion(version_id(doc.document_id, file.file_id, segment),
                                          doc.document_id, file.file_id, segment, stamp)
                repository.register_version(version)
                repository.associate_page(VersionPage(version.version_id, page, 0))
                version_ids.append(version.version_id)
                drafts = list(_leaves(payload))
                drafts.extend(_text_fact('legacy/' + k, str(row[k])) for k in
                              ('period_key', 'version_key', 'pdf_sha256', 'source_filename', 'payload'))
                drafts.append(_text_fact('legacy/resolution_status', 'UNRESOLVED'))
                content = canonical_sha256({d.fact_key: d.value for d in drafts})
                extraction = Extraction(extraction_id(version.version_id, 'alten-legacy-evidence', REVISION, config),
                                        version.version_id, 'alten-legacy-evidence', REVISION, config, content, stamp)
                repository.register_extraction(extraction)
                extraction_ids.append(extraction.extraction_id)
                for draft in drafts:
                    fact = DocumentaryFact.from_draft(extraction.extraction_id, draft, created_at=stamp)
                    repository.register_fact(fact)
                    if draft.fact_key.startswith('payload/'):
                        repository.associate_fact_page(FactPage(fact.fact_id, page))
                    facts.append(fact)
            assessment = Assessment.from_facts(doc.document_id, rule.rule_id, tuple(facts),
                                               'ambiguous' if len(group) > 1 else 'pending', created_at=stamp)
            repository.register_assessment(assessment)
            assessments.append(assessment.assessment_id)
    return AltenEvidenceResult(tuple(documents), tuple(version_ids), tuple(extraction_ids), tuple(assessments))
