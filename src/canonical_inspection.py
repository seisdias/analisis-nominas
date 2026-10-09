"""Read-only developer queries. No selection, economic policy or write API."""
import re
import sqlite3
from collections import Counter
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
from src.canonical.values import ExactDecimal
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

    def _documentary_context(self, document_id: str) -> dict[str, Any]:
        """Require agreement across every version/extraction, never select one."""
        names = ('empresa', 'cif', 'anio', 'mes')
        values: dict[str, set[str | int]] = {name: set() for name in names}
        issues: dict[str, set[str]] = {name: set() for name in names}
        versions = self._repo.get_document_versions(document_id)
        if not versions:
            for name in names:
                issues[name].add('missing_version')
        for version in versions:
            extraction_ids = [row[0] for row in self._connection.execute(
                'SELECT extraction_id FROM extractions WHERE version_id=? ORDER BY extraction_id',
                (version.version_id,))]
            if not extraction_ids:
                for name in names:
                    issues[name].add('missing_extraction')
            for identity in extraction_ids:
                facts = self._repo.get_extraction_facts(identity)
                for name in names:
                    matches = [f for f in facts if f.fact_key in ('nomina.' + name, 'payload/' + name)]
                    if not matches:
                        issues[name].add('missing_fact')
                    for fact in matches:
                        value = fact.value
                        if value.state != 'present':
                            issues[name].add('non_present.' + value.state)
                            continue
                        raw = value.value
                        if name in ('empresa', 'cif'):
                            if not isinstance(raw, str) or not raw.strip():
                                issues[name].add('invalid_value')
                            else:
                                values[name].add(raw)  # Exact text, no normalization.
                        elif isinstance(raw, ExactDecimal):
                            number = raw.to_decimal()
                            upper = 12 if name == 'mes' else 9999
                            if number != number.to_integral_value() or not 1 <= number <= upper:
                                issues[name].add('invalid_value')
                            else:
                                values[name].add(int(number))
                        else:
                            issues[name].add('invalid_value')
        for name in names:
            if len(values[name]) > 1:
                issues[name].add('conflicting_values')
        known = {name: not issues[name] and len(values[name]) == 1 for name in names}
        return {
            'company_text': next(iter(values['empresa'])) if known['empresa'] else None,
            'period': (next(iter(values['anio'])), next(iter(values['mes'])))
                      if known['anio'] and known['mes'] else None,
            'fields': {
                'company': (known['empresa'], tuple(sorted(issues['empresa']))),
                'cif': (known['cif'], tuple(sorted(issues['cif']))),
                'year_month': (known['anio'] and known['mes'],
                               tuple(sorted(issues['anio'] | issues['mes']))),
            },
        }

    def coverage(self) -> dict[str, Any]:
        """Structural coverage in this read snapshot, never economic inclusion."""
        rows = self._connection.execute(
            'SELECT d.document_id,d.employer_id,e.display_name FROM logical_documents d '
            'LEFT JOIN employers e ON e.employer_id=d.employer_id ORDER BY d.document_id').fetchall()
        documentary = {row[0]: self._documentary_context(row[0]) for row in rows}
        observations = []
        for (identity,) in self._connection.execute(
                'SELECT observation_id FROM economic_observations ORDER BY observation_id'):
            observations.append(self.explain(identity, CertificationRequirements()))
        versions = Counter(row[0] for row in self._connection.execute(
            'SELECT document_id FROM document_versions'))
        assessments = list(self._connection.execute('SELECT document_id,status FROM assessments'))
        relations = list(self._connection.execute(
            'SELECT source_document_id,target_document_id,relation_type FROM document_relations'))
        observation_relations = list(self._connection.execute(
            'SELECT source_observation_id,target_observation_id,relation_type FROM observation_relations'))

        total_facts = list(self._connection.execute(
            'SELECT v.document_id,f.fact_key,f.value_state FROM documentary_facts f '
            'JOIN extractions e ON e.extraction_id=f.extraction_id '
            'JOIN document_versions v ON v.version_id=e.version_id '
            "WHERE f.fact_key IN ('nomina.total_devengado','nomina.liquido_percibir')"))
        concept_rows = list(self._connection.execute(
            'SELECT v.document_id,f.extraction_id,f.fact_key,f.value_state '
            'FROM documentary_facts f JOIN extractions e ON e.extraction_id=f.extraction_id '
            'JOIN document_versions v ON v.version_id=e.version_id '
            "WHERE f.fact_key LIKE 'nomina.conceptos.%' ORDER BY f.fact_id"))

        def counts(ids: set[str]) -> dict[str, Any]:
            selected = [o for o in observations if o['document'].document_id in ids]
            obs_ids = {o['observation'].observation_id for o in selected}
            periods = {(o['document'].corpus_id, o['document'].employer_id,
                        o['observation'].liquidation_period.value) for o in selected
                       if o['observation'].liquidation_period.state == 'present'}
            known_docs = {o['document'].document_id for o in selected
                          if o['observation'].liquidation_period.state == 'present'}
            concepts = set()
            concept_docs = set()
            amount_states: Counter[str] = Counter()
            for doc, extraction, key, state in concept_rows:
                match = re.fullmatch(r'nomina\.conceptos\.([0-9a-f]{64})\.([0-9]+)\.([a-z_]+)', key)
                if doc in ids and match:
                    concepts.add((extraction, match[1], match[2]))
                    concept_docs.add(doc)
                    if match[3] == 'importe':
                        amount_states[state] += 1
            documentary_counts = {}
            for field in ('company', 'cif', 'year_month'):
                documentary_counts[field] = {
                    'known_documents': sum(documentary[i]['fields'][field][0] for i in ids),
                    'unavailable_documents': sum(not documentary[i]['fields'][field][0] for i in ids),
                    'diagnostics': dict(sorted(Counter(
                        reason for i in ids for reason in documentary[i]['fields'][field][1]).items())),
                }
            result: dict[str, Any] = {
                'documentary_context': documentary_counts,
                'documentary_concept_occurrences_per_extraction': len(concepts),
                'documents_with_concept_fields': len(concept_docs),
                'concept_amount_states': dict(sorted(amount_states.items())),
                'documents': len(ids), 'versions': sum(versions[i] for i in ids),
                'documents_with_multiple_versions': sum(versions[i] > 1 for i in ids),
                'observations': len(selected),
                'known_liquidation_periods': len(periods),
                'documents_without_known_liquidation_period': len(ids - known_docs),
                'eligibility': dict(sorted(Counter(o['observation'].eligibility for o in selected).items())),
                'assessment_states': dict(sorted(Counter(status for doc, status in assessments
                                                         if doc in ids).items())),
                'registered_document_relations': dict(sorted(Counter(
                    kind for a, b, kind in relations if a in ids or b in ids).items())),
                'registered_observation_relations': dict(sorted(Counter(
                    kind for a, b, kind in observation_relations if a in obs_ids or b in obs_ids).items())),
            }
            for magnitude in ('documentary_gross', 'documentary_net'):
                matching = [o for o in selected if o['observation'].magnitude == magnitude]
                certified = [o for o in matching if o['certification']['status'] == 'certified']
                covered = {o['document'].document_id for o in certified}
                observed = {o['document'].document_id for o in matching}
                reasons: Counter[str] = Counter()
                for o in matching:
                    cert = o['certification']
                    reasons.update(cert.get('reasons', ()))
                    if cert['status'] == 'NOT_EVALUATED':
                        reasons.update(['inspection.multiple_or_missing_extractions'])
                fact_key = ('nomina.total_devengado' if magnitude == 'documentary_gross'
                            else 'nomina.liquido_percibir')
                result[magnitude] = {
                    'documentary_fact_states_all_extractions': dict(sorted(Counter(
                        state for doc, key, state in total_facts if doc in ids and key == fact_key).items())),
                    'observations': len(matching), 'certified_observations': len(certified),
                    'certified_documents': len(covered),
                    'documents_without_observation': len(ids - observed),
                    'documents_without_certified_value': len(ids - covered),
                    'documents_with_multiple_observations': sum(
                        n > 1 for n in Counter(o['document'].document_id for o in matching).values()),
                    'value_states': dict(sorted(Counter(o['observation'].value.state
                                                        for o in matching).items())),
                    'certification_blockers_by_observation': dict(sorted(reasons.items())),
                }
            return result

        employers = sorted({row[1] for row in rows if row[1] is not None})
        if any(row[1] is None for row in rows):
            employers.append(None)
        companies = [{'employer_id': employer,
                      'company': next(row[2] for row in rows if row[1] == employer)
                                 if employer is not None else 'NO DISPONIBLE: empleador desconocido',
                      **counts({row[0] for row in rows if row[1] == employer})}
                     for employer in employers]
        textual_names = sorted({d['company_text'] for d in documentary.values()
                                if d['company_text'] is not None})
        if any(d['company_text'] is None for d in documentary.values()):
            textual_names.append(None)
        documentary_companies = []
        for name in textual_names:
            ids = {i for i, d in documentary.items() if d['company_text'] == name}
            documentary_companies.append({
                'company_text': name,
                'assignment': 'documentary_exact_text' if name is not None else 'NO DISPONIBLE: ambiguo o incompleto',
                'distinct_documentary_year_months': len({documentary[i]['period'] for i in ids
                                                         if documentary[i]['period'] is not None})
                                                     if name is not None else 'NO DISPONIBLE',
                **counts(ids),
            })
        return {
            'documentary_companies': documentary_companies,
            'documentary_definition': 'Texto exacto, sin identidad empresarial inferida. Año/mes documental '
                                      'no equivale a liquidación ni devengo. Se exige concordancia PRESENT '
                                      'en todas las versiones/extracciones. CIF: sólo cobertura, nunca valores.',
            'contract': 'canonical-coverage/v1', 'companies': companies,
            'total': counts({row[0] for row in rows}),
            'period_definition': 'Mes de liquidación PRESENT en observaciones; distintos por corpus/empleador/mes. '
                                 'No mide meses trabajados ni periodos documentales sin observación.',
            'concept_usability': 'NO DISPONIBLE: no hay certificación de utilidad económica de conceptos.',
            'notice': 'certified != candidate != additive; sin selección ni resolución. '
                      'Sin observación no significa ausencia documental. Conteos de versiones no se deduplican. '
                      'Relaciones registradas son contexto, no exclusiones. Requisitos contextuales NOT_EVALUATED.',
        }

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
