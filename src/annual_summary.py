"""Documentary company/year inventory. No cross-document monetary arithmetic."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from src.analysis_context import ContextFilters, Period, build_context
from src.document_concepts import DocumentConcepts
from src.documentary_coverage import CompanyYearCoverage, CoverageDocument, summarize_coverage
from src.economic_components import ComponentPoint, component_extraction, project_components
from src.income_evolution import project_income
from src.salary_reconstruction import (
    Indicator,
    Part,
    Reconstruction,
    identified_ordinary,
    reconstruct,
)


class Additivity(StrEnum):
    UNACCREDITED = "Aditividad anual no acreditada"
    REJECTED = "Aditividad rechazada para este conjunto"
    NON_ADDITIVE = "No aditivo con el bruto: componente incluido"
    ACCREDITED = "Aditividad acreditada por contrato"  # No annual producer exists.


@dataclass(frozen=True)
class AnnualDocument:
    record: CoverageDocument
    version_id: str | None
    extraction_id: str | None
    selection_reason: str
    no_breakdown: bool
    analysis_reason: str
    exclusion: str | None
    components: tuple[ComponentPoint, ...]
    component_parts: tuple[Part, ...]
    reconstruction: Reconstruction | None
    ordinary: Indicator | None
    component_relation: Additivity = Additivity.NON_ADDITIVE


@dataclass(frozen=True)
class AnnualGroup:
    coverage: CompanyYearCoverage
    documents: tuple[AnnualDocument, ...]
    window_months: tuple[int, ...]
    missing_months: tuple[int, ...]
    additivity: Additivity = Additivity.UNACCREDITED
    aggregate: None = None
    reason: str = (
        "Total anual no acreditado. No existe contrato de aditividad entre documentos que "
        "acredite independencia, compatibilidad temporal y unidad común. "
        "Certificación individual, candidate y resolución A.3 no autorizan la suma."
    )


@dataclass(frozen=True)
class AnnualReport:
    groups: tuple[AnnualGroup, ...]


def _rejection(documents: tuple[AnnualDocument, ...]) -> tuple[str, ...]:
    """Negative checks only, per original magnitude; never grant additivity.

    A presentation hold is not an economic exclusion. Missing units do not prove
    incompatibility. Values, filenames and dates are not identity heuristics.
    """
    owners: dict[str, set[str]] = {}
    currencies: dict[str, set[str]] = {}
    reasons = set()
    for item in documents:
        for observation in item.record.document.observations:
            if observation.magnitude not in ("documentary_gross", "documentary_net"):
                continue
            owners.setdefault(observation.observation_id, set()).add(item.record.document_id)
            if observation.eligibility == "excluded":
                reasons.add(
                    "El conjunto incluye una observación con elegibilidad canónica excluded."
                )
            currency = observation.value.currency
            if currency is not None:
                currencies.setdefault(observation.magnitude, set()).add(currency.code)
    if any(len(ids) > 1 for ids in owners.values()):
        reasons.add("Una misma observación se atribuye a documentos lógicos distintos.")
    if any(len(units) > 1 for units in currencies.values()):
        reasons.add(
            "Hay monedas explícitas incompatibles para una misma magnitud; no se convierten."
        )
    return tuple(sorted(reasons))


def annual_summary(
    records: Sequence[CoverageDocument],
    sources: Mapping[str, DocumentConcepts],
    blocked: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
    *,
    years: tuple[int, int],
    period: Period | None = None,
    uncertain: bool = False,
) -> AnnualReport:
    """Records are the panel's intersection; restrictions come from full C.3 context.

    Unknown context stays unassigned. A filtered month range never becomes a full
    year. Equal logical IDs are deduplicated by C.4.1, conflicting records rejected.
    No eligibility enum, temporal coverage or version decision is an annual license.
    """
    if period is not None:
        context = build_context(records, ContextFilters(period=period))
        records = context.documents
        uncertain = uncertain or context.gaps_uncertain
    coverage = summarize_coverage(records, years=years)
    docs = tuple(r.document for r in coverage.documents)
    income = project_income(docs, sources, blocked, totals)
    points = project_components(docs, sources, blocked).points
    items = {}
    for record in coverage.documents:
        d = record.document
        source = sources.get(d.document_id)
        selected = component_extraction(d, source)
        no_breakdown = source is not None and not any(e.concepts for e in source.extractions)
        # Selection and representation are separate. A held document can still
        # have an authorized version, but it does not contribute economic points.
        exclusion = blocked.get(d.document_id)
        if record.presentation_restricted:
            exclusion = exclusion or "Restricción local de representación"
        r = income.compositions.get(d.document_id) if exclusion is None else None
        ordinary = (
            identified_ordinary(selected)
            if r is not None and not isinstance(selected, str)
            else None
        )
        available_points = (
            tuple(p for p in points if p.occurrence.document_id == d.document_id)
            if exclusion is None
            else ()
        )
        individual_parts: tuple[Part, ...] = ()
        if r is None and available_points and not isinstance(selected, str):
            fact_ids = {p.amount.fact.fact_id for p in available_points}
            individual_parts = tuple(
                p
                for p in reconstruct(selected).parts
                if (f := p.source.source.get("importe")) is not None and f.fact.fact_id in fact_ids
            )
        items[d.document_id] = AnnualDocument(
            record,
            selected.version_id if not isinstance(selected, str) else None,
            selected.extraction_id if not isinstance(selected, str) else None,
            selected
            if isinstance(selected, str)
            else "Versión autorizada por A.3"
            if len(d.provenance) > 1
            else "Versión única",
            no_breakdown,
            next(
                (
                    d.get("Limitación", "")
                    for d in income.diagnostics
                    if d["Documento"] == record.document_id
                ),
                "",
            ),
            exclusion,
            available_points,
            r.parts if r is not None else individual_parts,
            r,
            ordinary,
        )
    groups = []
    for group in coverage.groups:
        months = tuple(
            m
            for m in range(1, 13)
            if group.year is not None
            and (period is None or period[0] <= (group.year, m) <= period[1])
        )
        if group.year is not None and not months:
            continue
        group_documents = tuple(items[i] for i in group.document_ids)
        rejected = _rejection(group_documents)
        result = AnnualGroup(
            replace(group, absence_certain=group.absence_certain and not uncertain),
            group_documents,
            months,
            tuple(m for m in group.missing_months if m in months),
        )
        if rejected:
            result = replace(
                result,
                additivity=Additivity.REJECTED,
                reason="Total anual no acreditado. Agregación rechazada para este conjunto: "
                + " ".join(rejected)
                + " No se elimina ningún documento ni se autoriza automáticamente un subconjunto.",
            )
        groups.append(result)
    return AnnualReport(tuple(groups))
