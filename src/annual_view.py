"""Annual documentary drill-down in the existing contextual panel."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import streamlit as st

from src.analysis_context import AnalysisContext, ContextFilters
from src.analytic_dataset import DocumentCategory
from src.annual_summary import AnnualGroup, AnnualReport, annual_summary
from src.canonical_inspection import InspectionError, open_inspector
from src.coverage_view import CATEGORIES
from src.document_concepts import read_document_concepts
from src.document_explorer import format_amount
from src.documentary_coverage import CoverageDocument
from src.gui_presentation import canonical_value_text, format_period, short_id
from src.salary_reconciliation import Status
from src.salary_reconstruction import Bucket


def load_annual(
    database: Path,
    records: Sequence[CoverageDocument],
    blocked: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
    *,
    years: tuple[int, int],
    filters: ContextFilters,
    uncertain: bool,
) -> AnnualReport:
    with open_inspector(database) as inspector:
        sources = {r.document_id: read_document_concepts(inspector, r.document_id) for r in records}
    return annual_summary(
        records, sources, blocked, totals, years=years, period=filters.period, uncertain=uncertain
    )


def summary_rows(report: AnnualReport) -> list[dict[str, Any]]:
    rows = []
    for g in report.groups:
        docs = g.documents

        def count_bucket(bucket: Bucket) -> int:
            return sum(any(p.bucket == bucket for p in d.component_parts) for d in docs)

        rows.append(
            {
                "Empresa documental": g.coverage.company or "Empresa desconocida",
                "Ejercicio documental": str(g.coverage.year)
                if g.coverage.year
                else "Sin año conocido",
                "Documentos": len(docs),
                "Meses documentados": ", ".join(f"{m:02d}" for m in g.coverage.months)
                or "Sin meses localizados",
                "Ventana": ", ".join(f"{m:02d}" for m in g.window_months) or "No determinada",
                "Meses sin documentación localizada": ", ".join(
                    f"{m:02d}" for m in g.missing_months
                )
                or "Ninguno en la ventana"
                if g.window_months
                else "No determinables",
                "Cobertura": "Incierta por contexto incompleto"
                if not g.coverage.absence_certain
                else "12 meses documentados; integridad salarial no acreditada"
                if len(g.coverage.months) == 12
                else "Cobertura parcial",
                "Ordinarias": sum(
                    d.record.document.category == DocumentCategory.ORDINARY for d in docs
                ),
                "Extras independientes": sum(
                    d.record.document.category == DocumentCategory.EXTRA for d in docs
                ),
                "Otros documentos": sum(
                    d.record.document.category
                    not in (DocumentCategory.ORDINARY, DocumentCategory.EXTRA)
                    for d in docs
                ),
                "Ordinarios parciales": sum(
                    d.ordinary is not None and d.ordinary.amount is not None for d in docs
                ),
                "Extras incluidas": count_bucket(Bucket.EXTRA),
                "Prorratas": count_bucket(Bucket.PRORATION),
                "Bonus": count_bucket(Bucket.VARIABLE),
                "Atrasos y ajustes": count_bucket(Bucket.ADJUSTMENT),
                "Función pendiente": count_bucket(Bucket.UNKNOWN),
                "Multiversión": sum(len(d.record.document.provenance) > 1 for d in docs),
                "Multiversión autorizada": sum(
                    len(d.record.document.provenance) > 1 and d.version_id is not None for d in docs
                ),
                "Multiversión no autorizada": sum(
                    len(d.record.document.provenance) > 1 and d.version_id is None for d in docs
                ),
                "Excluidos de representación": sum(d.exclusion is not None for d in docs),
                "Sin desglose": sum(d.no_breakdown for d in docs),
                "Con incidencias": sum(bool(d.record.review_reasons) for d in docs),
                "Diferencias no explicadas": sum(
                    d.reconstruction is not None
                    and d.reconstruction.earnings.status == Status.DIFFERENCE
                    for d in docs
                ),
                "Aditividad": g.additivity.value,
                "Total anual": "No acreditado",
            }
        )
    return rows


def _open_document() -> None:
    identity = st.session_state.get("annual_document")
    if identity in st.session_state.get("panel_valid_ids", ()):
        st.session_state["panel_document"] = identity


def _detail(group: AnnualGroup, records: Mapping[str, dict[str, Any]]) -> None:
    st.info(group.reason)
    st.caption(
        "Importes individuales del periodo documental. No equivalen a pagos del ejercicio ni a salario anual. Los componentes están incluidos en sus documentos, no son pagos adicionales."
    )
    documents = {d.record.document_id: d for d in group.documents}
    rows = []
    for identity, item in documents.items():
        raw = records[identity]
        rows.append(
            {
                "Periodo": format_period(item.record.year, item.record.month),
                "Documento": short_id(identity),
                "Categoría": CATEGORIES[item.record.document.category],
                "Bruto individual": format_amount(raw["gross"])
                if not item.exclusion
                else "Documento excluido; consulta ficha",
                "Neto individual": format_amount(raw["net"])
                if not item.exclusion
                else "Documento excluido; consulta ficha",
                "Representación": item.exclusion or "Importe documental individual",
                "Conceptos": "Desglose no disponible"
                if item.no_breakdown
                else item.selection_reason,
                "Limitaciones del desglose": item.analysis_reason,
            }
        )
    st.dataframe(
        rows,
        hide_index=True,
        column_config={
            name: st.column_config.TextColumn(alignment="right")
            for name in ("Bruto individual", "Neto individual")
        },
    )
    components = []
    for identity, item in documents.items():
        r = item.reconstruction
        if item.ordinary is not None and item.ordinary.amount is not None:
            components.append(
                {
                    "Documento": short_id(identity),
                    "Periodo": format_period(item.record.year, item.record.month),
                    "Componente": "Ordinario identificado (parcial)",
                    "Concepto": "Suma parcial B2b.3, no añadir a sus filas",
                    "Importe documentado": item.ordinary.amount.display(),
                    "Estado": "Calculado; cobertura parcial",
                }
            )
        if r is not None:
            for p in r.parts:
                label, amount = p.source.source.get("concepto"), p.source.source.get("importe")
                components.append(
                    {
                        "Documento": short_id(identity),
                        "Periodo": format_period(item.record.year, item.record.month),
                        "Componente": p.bucket.value,
                        "Concepto": canonical_value_text(label.fact.value)
                        if label
                        else "Sin denominación",
                        "Importe documentado": canonical_value_text(
                            amount.fact.value, monetary=True
                        )
                        if amount
                        else "No extraído",
                        "Estado": amount.fact.value.state.value if amount else "No extraído",
                    }
                )
        else:
            for point in item.components:
                label = point.occurrence.get("concepto")
                components.append(
                    {
                        "Documento": short_id(identity),
                        "Periodo": format_period(*point.period),
                        "Componente": point.component,
                        "Concepto": canonical_value_text(label.fact.value)
                        if label
                        else "Sin denominación",
                        "Importe documentado": canonical_value_text(
                            point.amount.fact.value, monetary=True
                        ),
                        "Estado": point.amount.fact.value.state.value,
                    }
                )
    if components:
        st.write("Componentes identificados, sin suma anual")
        st.dataframe(
            components,
            hide_index=True,
            column_config={"Importe documentado": st.column_config.TextColumn(alignment="right")},
        )
    else:
        st.caption(
            "Sin componentes representables en este grupo. Los documentos y sus limitaciones siguen disponibles en la ficha."
        )
    if st.session_state.get("annual_document") not in documents:
        st.session_state["annual_document"] = None
    st.selectbox(
        "Consultar una nómina del ejercicio",
        list(documents),
        index=None,
        key="annual_document",
        format_func=lambda i: f"{format_period(documents[i].record.year, documents[i].record.month)} · {CATEGORIES[documents[i].record.document.category]} · {short_id(i)}",
    )
    st.button(
        "Abrir ficha documental",
        key="annual_open",
        on_click=_open_document,
        disabled=st.session_state.get("annual_document") is None,
    )
    with st.expander("Procedencia, unidad y restricciones del ejercicio"):
        st.dataframe(
            [
                {
                    "Documento": i,
                    "Versión de conceptos": d.version_id or "Sin selección de conceptos",
                    "Extracción de conceptos": d.extraction_id or "No disponible",
                    "Observación": o.observation_id,
                    "Magnitud": o.magnitude,
                    "Elegibilidad": o.eligibility,
                    "Hechos del total": "; ".join(
                        dict(d.record.document.observation_facts).get(o.observation_id, ())
                    ),
                    "Moneda canónica": o.value.currency.code
                    if o.value.currency
                    else "No acreditada",
                    "Fecha de pago": canonical_value_text(o.payment_date),
                    "Restricción": d.exclusion
                    or "Ninguna de representación; aditividad anual pendiente",
                }
                for i, d in documents.items()
                for o in d.record.document.observations
            ],
            hide_index=True,
        )
        component_trace = []
        for identity, item in documents.items():
            occurrences = (
                tuple(p.source.source for p in item.reconstruction.parts)
                if item.reconstruction is not None
                else tuple(p.occurrence for p in item.components)
            )
            for occurrence in occurrences:
                for field, evidence in occurrence.attributes:
                    component_trace.append(
                        {
                            "Documento": identity,
                            "Versión": occurrence.version_id,
                            "Extracción": occurrence.extraction_id,
                            "Ocurrencia": occurrence.occurrence,
                            "Campo": field,
                            "Hecho": evidence.fact.fact_id,
                            "Clave": evidence.fact.fact_key,
                            "Estado": evidence.fact.value.state.value,
                            "Página": ", ".join(map(str, evidence.pages)) or "No registrada",
                        }
                    )
        if component_trace:
            st.dataframe(component_trace, hide_index=True)
        st.caption(
            "Las versiones/extracciones indicadas son de conceptos; los totales conservan sus observaciones y hechos propios. Accede a la ficha para la procedencia íntegra y las versiones alternativas."
        )


def render_annual(
    database: Path,
    context: AnalysisContext,
    filters: ContextFilters,
    records: Mapping[str, dict[str, Any]],
    blocked: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
) -> None:
    st.subheader("Resumen económico por ejercicio")
    st.caption(
        "Empresa y Periodo, arriba, delimitan esta vista. Usa un año o un intervalo de años para comparar cobertura y composición. Ocultar series no cambia el inventario. Ejercicio documental no significa año de cobro."
    )
    years = [d.year for d in context.documents if d.year is not None]
    bounds = (
        (filters.period[0][0], filters.period[1][0])
        if filters.period
        else (min(years), max(years))
        if years
        else (1, 1)
    )
    try:
        result = load_annual(
            database,
            context.documents,
            blocked,
            totals,
            years=bounds,
            filters=filters,
            uncertain=context.gaps_uncertain,
        )
    except InspectionError:
        st.error(
            "No se pudo consultar el resumen anual en solo lectura. No se han calculado totales."
        )
        return
    groups = {
        (g.coverage.company, g.coverage.year): g
        for g in result.groups
        if g.documents or filters.period
    }
    displayed = AnnualReport(tuple(groups.values()))
    st.caption(
        "Los recuentos de componentes indican documentos con evidencia representable. No son sumas monetarias. Doce meses documentados no acreditan todas las pagas ni un año salarial completo."
    )
    all_rows = summary_rows(displayed)
    primary = (
        "Empresa documental",
        "Ejercicio documental",
        "Documentos",
        "Meses documentados",
        "Ventana",
        "Cobertura",
        "Aditividad",
        "Total anual",
    )
    st.dataframe([{k: r[k] for k in primary} for r in all_rows], hide_index=True)
    with st.expander("Comparar cobertura, categorías y componentes entre ejercicios"):
        st.caption(
            "Comparación de recuentos documentales. No hay variaciones monetarias ni porcentajes de salario anual."
        )
        st.dataframe(all_rows, hide_index=True)
    if st.session_state.get("annual_group") not in groups:
        st.session_state["annual_group"] = None
    selected = st.selectbox(
        "Detalle de empresa y ejercicio",
        list(groups),
        index=None,
        key="annual_group",
        format_func=lambda g: f"{g[0] or 'Empresa desconocida'} · {g[1] or 'Sin año conocido'}",
    )
    if selected is not None:
        _detail(groups[selected], records)
