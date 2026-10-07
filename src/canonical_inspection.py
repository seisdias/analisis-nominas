"""Read-only developer queries. No selection, economic policy or write API."""
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Any

from src.canonical.certification import (
    CertificationRequirements,
    DocumentarySupport,
    certify_observation,
)
from src.persistence import CanonicalSQLiteError, connect, verify_schema
from src.persistence.economics import EconomicRepository


class InspectionError(ValueError):
    """Invalid database, missing record or unsupported inspection scope."""


def _required(value: Any, description: str) -> Any:
    if value is None:
        raise InspectionError(f'{description} not found')
    return value


class CanonicalInspector:
    """Used within open_inspector's read-only snapshot; returns data, never cursors."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._repo = EconomicRepository(connection)

    def summary(self) -> dict[str, Any]:
        tables = ('logical_documents', 'document_versions', 'documentary_facts',
                  'assessments', 'economic_observations')
        counts = {t: self._connection.execute(f'SELECT count(*) FROM {t}').fetchone()[0]
                  for t in tables}
        groups = {}
        for table, column in (('assessments', 'status'), ('economic_observations', 'economic_status'),
                              ('economic_observations', 'eligibility')):
            groups[f'{table}.{column}'] = dict(self._connection.execute(
                f'SELECT {column},count(*) FROM {table} GROUP BY {column} ORDER BY {column}'))
        return {'counts': counts, 'states': groups}

    def _ids(self, table: str, identity: str, filters: dict[str, str | None], limit: int) -> list[str]:
        # Table/column names come only from the fixed call sites below, never user SQL.
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise InspectionError('Limit must be between 1 and 1000')
        selected = {k: v for k, v in filters.items() if v is not None}
        where = ' AND '.join(f'{key}=?' for key in selected) or '1=1'
        return [row[0] for row in self._connection.execute(
            f'SELECT {identity} FROM {table} WHERE {where} ORDER BY {identity} LIMIT ?',
            (*selected.values(), limit))]

    def observations(self, *, magnitude: str | None = None, economic_status: str | None = None,
                     eligibility: str | None = None, limit: int = 50) -> list[Any]:
        ids = self._ids('economic_observations', 'observation_id', {
            'magnitude': magnitude, 'economic_status': economic_status, 'eligibility': eligibility}, limit)
        return [_required(self._repo.get_observation(i), 'Observation').observation for i in ids]

    def facts(self, *, extraction_id: str | None = None, fact_key: str | None = None,
              value_state: str | None = None, limit: int = 50) -> list[Any]:
        ids = self._ids('documentary_facts', 'fact_id', {
            'extraction_id': extraction_id, 'fact_key': fact_key, 'value_state': value_state}, limit)
        return [_required(self._repo.get_fact(i), 'Fact') for i in ids]

    def _version(self, identity: str) -> dict[str, Any]:
        version = _required(self._repo.get_version(identity), 'Version')
        file = _required(self._repo.get_source_file(version.file_id), 'Source file')
        extractions = [self._repo.get_extraction(row[0]) for row in self._connection.execute(
            'SELECT extraction_id FROM extractions WHERE version_id=? ORDER BY extraction_id', (identity,))]
        locations = [dict(zip(('corpus_id', 'relative_path', 'original_filename'), row, strict=True))
                     for row in self._connection.execute(
                         'SELECT corpus_id,relative_path,original_filename FROM file_locations '
                         'WHERE file_id=? ORDER BY corpus_id,relative_path', (file.file_id,))]
        return {'version': version, 'source_file': file, 'locations': locations,
                'pages': self._repo.get_version_pages(identity), 'extractions': extractions}

    def document(self, identity: str) -> dict[str, Any]:
        doc = _required(self._repo.get_document(identity), 'Document')
        versions = [self._version(row[0]) for row in self._connection.execute(
            'SELECT version_id FROM document_versions WHERE document_id=? ORDER BY version_id', (identity,))]
        return {'document': doc, 'versions': versions}

    def explain(self, identity: str, requirements: CertificationRequirements) -> dict[str, Any]:
        evidence = _required(self._repo.get_observation(identity), 'Observation')
        assessment = _required(self._repo.get_assessment(evidence.observation.assessment_id), 'Assessment')
        rule = _required(self._repo.get_rule(assessment.rule_id), 'Rule')
        document = _required(self._repo.get_document(assessment.document_id), 'Document')
        facts = tuple(_required(self._repo.get_fact(i.fact_id), 'Assessment fact') for i in assessment.inputs)
        extraction_ids = sorted({f.extraction_id for f in facts})
        extractions = [_required(self._repo.get_extraction(i), 'Extraction') for i in extraction_ids]
        versions = [self._version(i) for i in sorted({e.version_id for e in extractions})]
        context = {f.name: 'NOT_EVALUATED' for f in fields(requirements)}
        certification: dict[str, Any] = {'status': 'NOT_EVALUATED', 'context': context}
        if len(extractions) == 1:
            extraction = extractions[0]
            version = _required(self._repo.get_version(extraction.version_id), 'Version')
            result = certify_observation(evidence, DocumentarySupport(
                document, version, extraction, rule, assessment, facts), requirements)
            certification.update(status=result.value_status, reasons=result.value_reasons,
                                 context_reasons=result.context_reasons, contract=result.contract)
            for f in fields(requirements):
                if getattr(requirements, f.name):
                    # No inference: these diagnostics come exclusively from certification.
                    reason_by_field = {'currency': 'context.currency_unknown',
                        'employer': 'context.employer_unknown', 'liquidation_period': 'context.liquidation_unknown',
                        'accrual_interval': 'context.accrual_unknown', 'payment_date': 'context.payment_unknown'}
                    context[f.name] = ('BLOCKED' if reason_by_field[f.name] in result.context_reasons
                                       else 'SATISFIED')
        else:
            # T7.2 accepts one source extraction. Do not select one or fabricate support.
            certification['inspection_diagnostic'] = 'Certification requires one extraction; none selected'
        return {'observation': evidence.observation, 'certification': certification,
                'assessment': assessment, 'rule': rule, 'document': document,
                'versions': versions,
                'supporting_facts': [{'fact': _required(self._repo.get_fact(i), 'Supporting fact'),
                                     'pages': self._repo.get_fact_pages(i)} for i in evidence.fact_ids],
                'notice': 'certification != additivity; candidate != additive; no relations resolved'}


@contextmanager
def open_inspector(path: Path) -> Iterator[CanonicalInspector]:
    """Verify current schema without migration; one snapshot for each command.

    Canonical DELETE-journal databases only. WAL inspection is deliberately
    rejected before SQLite opens it: even mode=ro can create WAL sidecar files.
    No immutable=1 shortcut is used, as it could ignore live journal contents.
    """
    try:
        with path.open('rb') as handle:
            header = handle.read(20)
        if header[18:20] != b'\x01\x01':
            raise InspectionError('Expected canonical SQLite with DELETE journal (WAL unsupported)')
        with connect(path, mode='read_only') as connection:
            connection.execute('BEGIN')
            status = verify_schema(connection)
            if status.current_version != 8 or status.pending_versions:
                raise InspectionError('Inspector requires canonical schema v8; no migrations applied')
            yield CanonicalInspector(connection)
    except (OSError, sqlite3.Error, CanonicalSQLiteError, ValueError, TypeError) as error:
        raise InspectionError(f'Cannot inspect canonical database: {error}') from error
