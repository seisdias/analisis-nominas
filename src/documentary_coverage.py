"""Immutable documentary counts, not economic inclusion or monetary aggregation."""
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.analytic_dataset import AnalyticDocument, DocumentCategory, read_analytic_dataset
from src.canonical_inspection import InspectionError, open_inspector


class Availability(StrEnum):
    CERTIFIED = 'certified'
    NO_OBSERVATION = 'no_observation'
    NOT_CERTIFIED = 'not_certified'
    AMBIGUOUS = 'ambiguous'


class ReviewReason(StrEnum):
    CONTEXT_INCOMPLETE = 'context.incomplete'
    CATEGORY_UNCLASSIFIED = 'category.unclassified'
    OBSERVATION_MISSING = 'observation.missing'
    OBSERVATION_AMBIGUOUS = 'observation.ambiguous'
    CERTIFICATION_BLOCKED = 'certification.blocked'


@dataclass(frozen=True, slots=True)
class CoverageDocument:
    document: AnalyticDocument
    company: str | None
    year: int | None
    month: int | None
    gross: Availability
    net: Availability
    presentation_restricted: bool = False

    @property
    def document_id(self) -> str:
        return self.document.document_id

    @property
    def review_reasons(self) -> tuple[ReviewReason, ...]:
        reasons = []
        if self.company is None or self.year is None or self.month is None:
            reasons.append(ReviewReason.CONTEXT_INCOMPLETE)
        if self.document.category == DocumentCategory.UNCLASSIFIED:
            reasons.append(ReviewReason.CATEGORY_UNCLASSIFIED)
        for state, reason in (
            (Availability.NO_OBSERVATION, ReviewReason.OBSERVATION_MISSING),
            (Availability.AMBIGUOUS, ReviewReason.OBSERVATION_AMBIGUOUS),
            (Availability.NOT_CERTIFIED, ReviewReason.CERTIFICATION_BLOCKED),
        ):
            if state in (self.gross, self.net):
                reasons.append(reason)
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class CompanyYearCoverage:
    company: str | None
    year: int | None
    document_ids: tuple[str, ...]
    months: tuple[int, ...]
    missing_months: tuple[int, ...]
    absence_certain: bool


@dataclass(frozen=True, slots=True)
class CoverageReport:
    documents: tuple[CoverageDocument, ...]
    groups: tuple[CompanyYearCoverage, ...]
    gross: tuple[tuple[Availability, tuple[str, ...]], ...]
    net: tuple[tuple[Availability, tuple[str, ...]], ...]
    categories: tuple[tuple[DocumentCategory, tuple[str, ...]], ...]

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents)

    @property
    def certified_both(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents
                     if d.gross == d.net == Availability.CERTIFIED)

    @property
    def analytic_gross(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents if d.document.gross is not None)

    @property
    def analytic_net(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents if d.document.net is not None)

    @property
    def multiversion_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents if len(d.document.provenance) > 1)

    @property
    def review_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents if d.review_reasons)

    @property
    def restricted_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents if d.presentation_restricted)


def summarize_coverage(records: Sequence[CoverageDocument], *, years: tuple[int, int],
                       company: str | None = None) -> CoverageReport:
    """Exact documentary names and logical IDs. Unknown years stay unassigned.

    Empty years in the requested interval remain visible. Missing context anywhere
    in the relevant source scope prevents claiming certain absence. A local hold
    never removes a document, changes certification or marks a version unresolved.
    """
    if any(type(y) is not int for y in years) or not 1 <= years[0] <= years[1] <= 9999:
        raise ValueError('Expected an inclusive year interval within 1..9999')
    unique: dict[str, CoverageDocument] = {}
    for record in records:
        if record.document_id in unique and unique[record.document_id] != record:
            raise ValueError('Conflicting coverage records for one document')
        unique[record.document_id] = record
    source = tuple(unique[key] for key in sorted(unique))
    selected = tuple(d for d in source if (company is None or d.company == company)
                     and (d.year is None or years[0] <= d.year <= years[1]))
    names = sorted({d.company for d in source if company is None or d.company == company},
                   key=lambda name: (name is None, name or ''))
    groups = []
    for name in names:
        for year in (*range(years[0], years[1] + 1), None):
            docs = tuple(d for d in selected if d.company == name and d.year == year)
            if year is None and not docs:
                continue
            months = tuple(sorted({d.month for d in docs if d.month is not None}))
            uncertain = name is None or year is None or any(
                (d.company is None or d.company == name) and (d.year is None or d.year == year)
                and (d.company is None or d.year is None or d.month is None) for d in source)
            groups.append(CompanyYearCoverage(name, year, tuple(d.document_id for d in docs),
                months, tuple(m for m in range(1, 13) if m not in months) if year else (),
                not uncertain))
    return CoverageReport(selected, tuple(groups),
        tuple((s, tuple(d.document_id for d in selected if d.gross == s)) for s in Availability),
        tuple((s, tuple(d.document_id for d in selected if d.net == s)) for s in Availability),
        tuple((c, tuple(d.document_id for d in selected if d.document.category == c)) for c in DocumentCategory))


def load_coverage(database: Path, *, withheld_document_ids: tuple[str, ...] = ()) -> tuple[CoverageDocument, ...]:
    """Both availability definitions come from ONE verified read-only snapshot."""
    with open_inspector(database) as inspector:
        rows = {r['document_id']: r for r in inspector.documents()}
        dataset = read_analytic_dataset(inspector)
        if set(rows) != {d.document_id for d in dataset}:
            raise InspectionError('Inconsistent documentary coverage snapshot')
        return tuple(CoverageDocument(d, rows[d.document_id]['company_text'],
            rows[d.document_id]['year'], rows[d.document_id]['month'],
            Availability(rows[d.document_id]['gross']['status']),
            Availability(rows[d.document_id]['net']['status']), d.document_id in withheld_document_ids)
            for d in sorted(dataset, key=lambda d: d.document_id))
