"""Presentation projection over B1 provenance and B2b arithmetic; no database access."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.analytic_dataset import AnalyticDocument, DocumentCategory
from src.canonical.values import ValueState
from src.document_concepts import DocumentConcepts
from src.economic_components import (
    ComponentPoint,
    component_extraction,
    component_rows,
    documentary_block,
    project_components,
)
from src.salary_reconciliation import Status
from src.salary_reconstruction import Bucket, identified_ordinary, reconstruct

GROSS = "Bruto documental"
ORDINARY = "Ordinario identificado (parcial)"
EXTRA = "Extras identificadas"
PRORATION = "Prorratas salariales identificadas"
VARIABLE = "Bonus/variable identificado"
ADJUSTMENT = "Atrasos y ajustes identificados"
INDEPENDENT = "Extras identificadas (documento independiente)"
SERIES = (GROSS, ORDINARY, EXTRA, PRORATION, VARIABLE, ADJUSTMENT, INDEPENDENT)
_LABELS = {
    "Extra de verano incluida": EXTRA,
    "Extra de Navidad incluida": EXTRA,
    "Prorratas de extras": PRORATION,
    "Bonus / variable": VARIABLE,
    "Ajustes de extras": ADJUSTMENT,
}


@dataclass(frozen=True)
class IncomeProjection:
    rows: list[dict[str, Any]]
    diagnostics: tuple[dict[str, str], ...]


def visible_income(rows: Sequence[dict[str, Any]], selected: Sequence[str]) -> list[dict[str, Any]]:
    return [r for r in rows if r["Componente"] in selected]


def project_income(
    documents: Sequence[AnalyticDocument],
    sources: Mapping[str, DocumentConcepts],
    blocked: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
) -> IncomeProjection:
    """Totals are already certified/guarded timeline points, never recomputed here.

    Visibility follows this full-context projection. Partial sums never establish
    temporal continuity, contractual recurrence or complete ordinary coverage.
    """
    rows: list[dict[str, Any]] = []
    diagnostics = []
    counts = Counter(d.document_id for d in documents)
    docs = {d.document_id: d for d in documents if counts[d.document_id] == 1}
    total_counts = Counter(p["Documento"] for p in totals if p["Serie"] == "Bruto")
    for p in totals:
        identity = p["Documento"]
        if (
            p["Serie"] != "Bruto"
            or identity not in docs
            or identity in blocked
            or total_counts[identity] != 1
        ):
            continue
        doc = docs[identity]
        rows.append(
            dict(
                p,
                Componente=INDEPENDENT if doc.category == DocumentCategory.EXTRA else GROSS,
                **{
                    "Periodo del documento": p["Fecha"][5:7] + "/" + p["Fecha"][:4],
                    "Cobertura": "Total documental certificado; no salario ordinario",
                    "Fórmula": "Valor documental, sin cálculo",
                    "Moneda canónica": doc.currency.code if doc.currency else "No acreditada",
                    "Versión": "; ".join(v.version_id for v in doc.provenance),
                    "Estado": "Certificación existente; evidence_only permanece intacto",
                },
            )
        )
    for doc in sorted(documents, key=lambda d: d.document_id):
        identity = doc.document_id
        reason = documentary_block(doc, blocked)
        if counts[identity] != 1:
            reason = "Identidad documental duplicada"
        if reason:
            diagnostics.append(
                {
                    "Documento": identity,
                    "Explicación": "Sin explicación suficiente",
                    "Limitación": reason,
                }
            )
            continue
        source = sources.get(identity)
        selected = component_extraction(doc, source)
        if isinstance(selected, str):
            diagnostics.append(
                {
                    "Documento": identity,
                    "Explicación": "Sin explicación suficiente",
                    "Limitación": selected,
                }
            )
            continue
        e = selected
        r = reconstruct(e)
        # Reuse reconstruction's occurrence integrity checks, before B1 components.
        if r.earnings.status == Status.CONFLICT or (
            r.period is not None and r.period != doc.documentary_period
        ):
            diagnostics.append(
                {
                    "Documento": identity,
                    "Explicación": "Sin explicación suficiente",
                    "Limitación": "Procedencia o periodo incompatible",
                }
            )
            continue
        ordinary = identified_ordinary(e)
        assert (
            doc.company_text is not None
            and doc.documentary_period is not None
            and source is not None
        )
        b1 = project_components((doc,), {identity: source}, blocked)
        component_points = list(b1.points)
        represented = {p.amount.fact.fact_id for p in component_points}
        # Additional explicit arrears/adjustments from B2a, never a second label catalog.
        for part in r.parts:
            amount = part.source.source.get("importe")
            if (
                part.bucket == Bucket.ADJUSTMENT
                and part.amount is not None
                and amount
                and amount.fact.fact_id not in represented
                and (amount.fact.value.currency is None or amount.fact.value.currency.code == "EUR")
            ):
                component_points.append(
                    ComponentPoint(
                        ADJUSTMENT,
                        doc.company_text,
                        doc.documentary_period,
                        part.source.source,
                        amount,
                        e.extractor_name,
                        e.extractor_revision,
                    )
                )
                represented.add(amount.fact.fact_id)
        explicit_currencies = {
            f.fact.value.currency.code if f.fact.value.currency else None
            for p in r.parts
            if (f := p.source.source.get("importe")) is not None
            and f.fact.value.state == ValueState.PRESENT
        }
        incompatible = any(c not in (None, "EUR") for c in explicit_currencies)
        if incompatible:
            diagnostics.append(
                {
                    "Documento": identity,
                    "Explicación": "Sin explicación suficiente",
                    "Limitación": "Divisa explícita incompatible; no se convierte a EUR",
                }
            )
            continue
        for row in component_rows(component_points):
            row["Componente"] = _LABELS.get(row["Componente"], row["Componente"])
            row["Cobertura"] = "Componente individual identificado; no salario completo"
            row["Fórmula"] = "Importe de la ocurrencia original; no se añade al bruto"
            rows.append(row)
        gross_support = [p for p in totals if p["Documento"] == identity and p["Serie"] == "Bruto"]
        comparison_supported = (
            len(gross_support) == 1
            and r.earnings.target is not None
            and r.earnings.target.fact.fact_id
            in dict(doc.observation_facts).get(gross_support[0]["Observación"], ())
        )
        if ordinary.amount is not None and comparison_supported:
            support = ordinary.participants
            labels = [
                str(label.fact.value.value)
                for c in e.concepts
                if (label := c.get("concepto")) is not None and c.get("importe") in support
            ]
            year, month = doc.documentary_period
            rows.append(
                {
                    "Fecha": f"{year:04d}-{month:02d}-01",
                    "Empresa": doc.company_text,
                    "Componente": ORDINARY,
                    "Importe": float(ordinary.amount.numerator),
                    "Importe exacto": format(
                        ordinary.amount.numerator,
                        f",.{max(2, -int(ordinary.amount.numerator.as_tuple().exponent))}f",
                    )
                    .replace(",", "_")
                    .replace(".", ",")
                    .replace("_", "."),
                    "Documento": identity,
                    "Periodo del documento": f"{month:02d}/{year}",
                    "Versión": e.version_id,
                    "Extracción": e.extraction_id,
                    "Hecho": "; ".join(f.fact.fact_id for f in support),
                    "Clave original": "; ".join(f.fact.fact_key for f in support),
                    "Etiqueta original": "; ".join(labels),
                    "Fórmula": ordinary.formula,
                    "Cobertura": ordinary.coverage.value + "; no salario fijo completo",
                    "Estado": ordinary.knowledge.value + "; no nueva certificación",
                    "Moneda canónica": support[0].fact.value.currency.code
                    if support[0].fact.value.currency
                    else "No acreditada",
                    "Páginas": "; ".join(
                        str(n) for n in sorted({n for f in support for n in f.pages})
                    ),
                    "Contrato": "; ".join(ordinary.evidence),
                }
            )
        known = [p for p in r.parts if p.bucket != Bucket.UNKNOWN and p.amount is not None]
        full = r.earnings.status == Status.RECONCILED and bool(known) and len(known) == len(r.parts)
        explanation = (
            "Desglose explicado completamente"
            if full
            else "Desglose explicado parcialmente"
            if known
            else "Sin explicación suficiente"
        )
        diagnostics.append(
            {
                "Documento": identity,
                "Explicación": explanation,
                "Limitación": ordinary.reason
                + " "
                + r.earnings.reason
                + (
                    ""
                    if comparison_supported
                    else " No coincide el soporte del bruto representado con esta extracción."
                ),
                "Fijo equivalente": "No determinable: cobertura, recurrencia y modalidad anual no acreditadas",
                "Conceptos pendientes": str(
                    sum(p.bucket == Bucket.UNKNOWN or p.amount is None for p in r.parts)
                ),
                "Periodo del documento": f"{doc.documentary_period[1]:02d}/{doc.documentary_period[0]}",
            }
        )
    return IncomeProjection(
        sorted(
            rows,
            key=lambda r: (
                r["Fecha"],
                r["Empresa"],
                r["Documento"],
                r["Componente"],
                r.get("Hecho", ""),
            ),
        ),
        tuple(diagnostics),
    )
