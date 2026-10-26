"""Read-only document projection for CLI/GUI; not aggregation or candidacy.

One record per logical document. Exact documentary labels are not employer
identities; documentary year/month is not an economic liquidation period.
Version resolution is unavailable in the current acknowledgement-only decision
contract, so resolved_version_id remains None, including single-version records.
"""
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.canonical.certification import CertificationRequirements, EconomicEligibility
from src.canonical.economics import EconomicObservation
from src.canonical.facts import DocumentaryFact
from src.canonical.values import CanonicalValue, CurrencyCode, ValueState
from src.canonical_inspection import CanonicalInspector, open_inspector


class DocumentCategory(StrEnum):
    ORDINARY = 'ordinary_payroll'
    EXTRA = 'extra_pay'
    VARIABLE_BONUS = 'variable_bonus'
    BENEFITS = 'benefits_pay'
    ARREARS_ADJUSTMENT = 'arrears_adjustment'
    SETTLEMENT = 'settlement'
    OTHER = 'other_economic_document'
    UNCLASSIFIED = 'unclassified'


class DatasetDiagnostic(StrEnum):
    MULTIPLE_VERSIONS = 'multiple_versions'
    AMBIGUOUS_OBSERVATIONS = 'ambiguous_observations'
    MISSING_VERSION = 'missing_version'
    TYPE_CONFLICT = 'type_conflict'
    TYPE_UNCERTAIN = 'type_uncertain'
    GROSS_UNAVAILABLE = 'gross_unavailable'
    NET_UNAVAILABLE = 'net_unavailable'
    INCOMPATIBLE_CURRENCIES = 'incompatible_currencies'
    CURRENCY_UNKNOWN = 'currency_unknown'
    COMPANY_UNCERTAIN = 'company_uncertain'
    PERIOD_UNCERTAIN = 'documentary_period_uncertain'


# Only the explicit current documentary vocabulary. No concept-level inference.
_CATEGORIES = {
    'NOMINA_ORDINARIA': DocumentCategory.ORDINARY,
    'PAGA_EXTRA': DocumentCategory.EXTRA,
    'FINIQUITO': DocumentCategory.SETTLEMENT,
    'VARIABLE_BONUS': DocumentCategory.VARIABLE_BONUS,
    'CERTIFICADO_RETENCIONES': DocumentCategory.OTHER,
}
_CONTEXT_KEYS = tuple(prefix + name for prefix in ('nomina.', 'payload/')
                      for name in ('empresa', 'anio', 'mes', 'tipo', 'fecha_inicio', 'fecha_fin'))


@dataclass(frozen=True, slots=True)
class VersionProvenance:
    version_id: str
    file_id: str
    file_sha256: str
    pages: tuple[int, ...]
    extraction_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalyticDocument:
    document_id: str
    corpus_id: str
    employer_id: str | None
    company_text: str | None
    documentary_period: tuple[int, int] | None
    category: DocumentCategory
    original_document_type: str
    classification_document_id: str
    classification_contract: str
    context_facts: tuple[DocumentaryFact, ...]
    resolved_version_id: str | None
    gross: CanonicalValue | None
    net: CanonicalValue | None
    currency: CurrencyCode | None
    eligibilities: tuple[EconomicEligibility, ...]
    diagnostics: tuple[DatasetDiagnostic, ...]
    observations: tuple[EconomicObservation, ...]
    observation_facts: tuple[tuple[str, tuple[str, ...]], ...]
    provenance: tuple[VersionProvenance, ...]

    @property
    def economic_liquidation_periods(self) -> tuple[CanonicalValue, ...]:
        """Original states, aligned with observations; no documentary fallback."""
        return tuple(o.liquidation_period for o in self.observations)


def read_analytic_dataset(inspector: CanonicalInspector) -> tuple[AnalyticDocument, ...]:
    """Project within the caller's existing inspector snapshot, without opening another."""
    result = []
    for row in inspector.documents():
        identity = row['document_id']
        detail = inspector.document(identity)
        doc = detail['document']
        provenance = []
        context_facts = []
        for version in detail['versions']:
            provenance.append(VersionProvenance(
                version['version'].version_id, version['source_file'].file_id,
                version['source_file'].sha256,
                tuple(p.page_number for p in version['pages']),
                tuple(e.extraction_id for e in version['extractions'])))
            for extraction in version['extractions']:
                for key in _CONTEXT_KEYS:
                    # At most one fact per extraction/key by canonical identity.
                    context_facts.extend(inspector.facts(
                        extraction_id=extraction.extraction_id, fact_key=key, limit=1))
        observations: dict[str, EconomicObservation] = {}
        links = {}
        # Read every observation of this document, including unsupported magnitudes.
        # document() supplies versions, while timeline alone would omit other magnitudes.
        for item in inspector.observations_for_document(identity):
            observation = item.observation
            observations[observation.observation_id] = observation
            links[observation.observation_id] = item.fact_ids
        diagnostics: set[DatasetDiagnostic] = set()
        category = _CATEGORIES.get(doc.document_type, DocumentCategory.UNCLASSIFIED)
        type_facts = [f for f in context_facts if f.fact_key in ('nomina.tipo', 'payload/tipo')]
        if any(f.value.state != ValueState.PRESENT for f in type_facts):
            diagnostics.add(DatasetDiagnostic.TYPE_UNCERTAIN)
            category = DocumentCategory.UNCLASSIFIED
        if any(f.value.state == ValueState.PRESENT and f.value.value != doc.document_type
               for f in type_facts):
            diagnostics.add(DatasetDiagnostic.TYPE_CONFLICT)
            category = DocumentCategory.UNCLASSIFIED
        if len(provenance) != 1:
            diagnostics.add(DatasetDiagnostic.MULTIPLE_VERSIONS if provenance
                            else DatasetDiagnostic.MISSING_VERSION)
        if row['company_text'] is None:
            diagnostics.add(DatasetDiagnostic.COMPANY_UNCERTAIN)
        period = ((row['year'], row['month']) if row['year'] is not None
                  and row['month'] is not None else None)
        if period is None:
            diagnostics.add(DatasetDiagnostic.PERIOD_UNCERTAIN)
        amounts: dict[str, CanonicalValue | None] = {}
        for field, magnitude, reason in (
            ('gross', 'documentary_gross', DatasetDiagnostic.GROSS_UNAVAILABLE),
            ('net', 'documentary_net', DatasetDiagnostic.NET_UNAVAILABLE),
        ):
            matches = [o for o in observations.values() if o.magnitude == magnitude]
            if len(matches) > 1:
                diagnostics.add(DatasetDiagnostic.AMBIGUOUS_OBSERVATIONS)
            amount = None
            if len(provenance) == 1 and len(matches) == 1:
                explained = inspector.explain(matches[0].observation_id, CertificationRequirements())
                if explained['certification']['status'] == 'certified':
                    amount = matches[0].value
            amounts[field] = amount
            if amount is None:
                diagnostics.add(reason)
        currencies = {a.currency for a in amounts.values() if a is not None and a.currency is not None}
        currency = None
        if len(currencies) > 1:
            diagnostics.add(DatasetDiagnostic.INCOMPATIBLE_CURRENCIES)
        elif all(a is not None and a.currency is not None for a in amounts.values()):
            currency = next(iter(currencies))
        else:
            diagnostics.add(DatasetDiagnostic.CURRENCY_UNKNOWN)
        ids = sorted(observations)
        result.append(AnalyticDocument(
            identity, doc.corpus_id, doc.employer_id, row['company_text'], period, category,
            doc.document_type, identity, 'documentary-classification/c1-v1',
            tuple(sorted(context_facts, key=lambda f: f.fact_id)), None,
            amounts['gross'], amounts['net'], currency,
            tuple(sorted({EconomicEligibility(o.eligibility) for o in observations.values()})),
            tuple(sorted(diagnostics)), tuple(observations[i] for i in ids),
            tuple((i, links[i]) for i in ids), tuple(provenance)))
    return tuple(sorted(result, key=lambda r: (
        r.documentary_period is None, r.documentary_period or (9999, 12), r.document_id)))


def load_analytic_dataset(database: str | Path) -> tuple[AnalyticDocument, ...]:
    """Verified v8 read-only snapshot; rejects WAL like the existing inspector."""
    with open_inspector(Path(database)) as inspector:
        return read_analytic_dataset(inspector)
