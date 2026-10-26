"""Pure documentary intersection and automatic presentation context."""
import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.documentary_coverage import CoverageDocument, CoverageReport, summarize_coverage

Month = tuple[int, int]
Period = tuple[Month, Month]


def parse_period(text: str) -> Period | None:
    """Blank, YYYY, MM/YYYY, or inclusive endpoints separated by a dash."""
    if not text.strip():
        return None
    parts = re.split(r'\s*[-–—]\s*', text.strip())
    if len(parts) > 2:
        raise ValueError('Usa un año, MM/AAAA o un intervalo como 03/2015 – 09/2015.')
    bounds = []
    for i, part in enumerate((parts[0], parts[-1])):
        match = re.fullmatch(r'(?:(0?[1-9]|1[0-2])/)?([0-9]{4})', part)
        if match is None or int(match[2]) == 0:
            raise ValueError('Usa un año válido o MM/AAAA; por ejemplo, 2015 o 09/2022.')
        bounds.append((int(match[2]), int(match[1]) if match[1] else (1 if i == 0 else 12)))
    if bounds[0] > bounds[1]:
        raise ValueError('El inicio del periodo debe ser anterior o igual al final.')
    return bounds[0], bounds[1]


@dataclass(frozen=True)
class ContextFilters:
    company: str | None = None
    period: Period | None = None
    incomplete_only: bool = False
    document_id: str | None = None


@dataclass(frozen=True)
class AnalysisContext:
    candidates: tuple[CoverageDocument, ...]
    documents: tuple[CoverageDocument, ...]
    selected_id: str | None
    stale_selection: bool
    level: str
    report: CoverageReport
    months: tuple[Month, ...]
    missing_months: tuple[Month, ...]
    gaps_uncertain: bool


def build_context(records: Sequence[CoverageDocument], filters: ContextFilters) -> AnalysisContext:
    unique: dict[str, CoverageDocument] = {}
    for record in records:
        if record.document_id in unique and unique[record.document_id] != record:
            raise ValueError('Conflicting context records for one logical document')
        unique[record.document_id] = record
    source = tuple(unique[k] for k in sorted(unique))
    if filters.period is not None:
        start, end = filters.period
        if not (1 <= start[0] <= 9999 and 1 <= end[0] <= 9999
                and 1 <= start[1] <= 12 and 1 <= end[1] <= 12 and start <= end):
            raise ValueError('Invalid inclusive month interval')
    candidates = tuple(d for d in source
        if (filters.company is None or d.company == filters.company)
        and (not filters.incomplete_only or d.company is None or d.year is None or d.month is None)
        and (filters.period is None or (d.year is not None and d.month is not None
             and filters.period[0] <= (d.year, d.month) <= filters.period[1])))
    selected = filters.document_id if any(d.document_id == filters.document_id for d in candidates) else None
    documents = tuple(d for d in candidates if selected is None or d.document_id == selected)
    level = ('document' if selected else 'month' if filters.period and filters.period[0] == filters.period[1]
             else 'period' if filters.period else 'company' if filters.company is not None else 'history')
    years = [d.year for d in documents if d.year is not None]
    report = summarize_coverage(documents, years=(min(years), max(years)) if years else (1, 1))
    months = tuple(sorted({(d.year, d.month) for d in documents if d.year is not None and d.month is not None}))
    missing: tuple[Month, ...] = ()
    if filters.period is not None and selected is None:
        a, b = filters.period
        missing = tuple((i // 12, i % 12 + 1) for i in range(a[0] * 12 + a[1] - 1, b[0] * 12 + b[1])
                        if (i // 12, i % 12 + 1) not in months)
    # Incomplete source context can belong to a gap even when strict filters
    # correctly exclude it. Do not silently claim certain documentary absence.
    uncertain = filters.incomplete_only or any(
        (filters.company is None or d.company is None or d.company == filters.company)
        and (d.year is None or d.month is None or d.company is None)
        and (filters.period is None or d.year is None or filters.period[0][0] <= d.year <= filters.period[1][0])
        for d in source)
    return AnalysisContext(candidates, documents, selected, filters.document_id is not None and selected is None,
                           level, report, months, missing, uncertain)
