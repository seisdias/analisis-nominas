"""First ordinary-income comparison within the existing contextual panel."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import altair as alt
import streamlit as st

from src.analytic_dataset import AnalyticDocument
from src.canonical_inspection import InspectionError, open_inspector
from src.component_view import component_chart, component_visibility
from src.document_concepts import read_document_concepts
from src.economic_components import documentary_block
from src.income_evolution import GROSS, SERIES, IncomeProjection, project_income, visible_income


def load_income(
    database: Path,
    documents: Sequence[AnalyticDocument],
    restrictions: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
) -> IncomeProjection:
    with open_inspector(database) as inspector:
        sources = {
            d.document_id: read_document_concepts(inspector, d.document_id)
            for d in documents
            if documentary_block(d, restrictions) is None
        }
    return project_income(documents, sources, restrictions, totals)


def income_chart(rows: list[dict[str, Any]]) -> alt.Chart | alt.FacetChart:
    # Reuse B1 marks/tooltips. Separate exact company and monetary evidence instead
    # of implying currency equivalence or joining incomplete ordinary observations.
    prepared = [
        dict(r, Empresa=r["Empresa"] + " · " + r.get("Moneda canónica", "No acreditada"))
        for r in rows
    ]
    chart = component_chart(prepared, components=SERIES)
    if isinstance(chart, alt.Chart):
        return chart.facet(row=alt.Row("Empresa:N", title=None))
    return chart


def render_income(
    database: Path,
    documents: Sequence[AnalyticDocument],
    restrictions: Mapping[str, str],
    totals: Sequence[dict[str, Any]],
    *,
    key: str,
    show_chart: bool = True,
) -> None:
    st.subheader("Evolución retributiva identificada")
    st.caption(
        "Compara bruto documental y partidas identificadas. El ordinario parcial no es salario fijo total. "
        "Los componentes ya están incluidos en el bruto: no se suman a él. "
        "Puntos individuales, sin interpolación ni continuidad salarial inferida."
    )
    try:
        result = load_income(database, documents, restrictions, totals)
    except InspectionError:
        st.error("No se pudo consultar la evolución retributiva en solo lectura.")
        return
    if result.rows and any(r["Componente"] != GROSS for r in result.rows):
        selection = component_visibility(
            {r["Componente"] for r in result.rows},
            key=key,
            options=SERIES,
            label="Series de retribución visibles",
            reset_label="Restablecer series",
        )
        rows = visible_income(result.rows, selection)
        if rows and show_chart:
            st.altair_chart(income_chart(rows), width="stretch")
        elif rows:
            st.dataframe(
                [{k: v for k, v in r.items() if k != "Importe"} for r in rows], hide_index=True
            )
        else:
            st.info("Series ocultas; la cobertura documental y los filtros permanecen intactos.")
        with st.expander("Inspeccionar importes y componentes de cada punto"):
            st.dataframe(
                [
                    {k: v for k, v in r.items() if k not in ("Importe", "Tramo", "Multipago")}
                    for r in rows
                ],
                hide_index=True,
            )
    else:
        st.info(
            "Sin componentes para comparar en este contexto; el bruto permanece en la gráfica documental. No se sustituyen ausencias por ceros."
        )
    st.caption(
        "Fijo mensual/anual equivalente: no determinable sin cobertura, periodicidad y modalidad acreditadas. "
        "El eje usa el periodo del documento, no fecha de cobro ni devengo. "
        "EUR es una convención visual; moneda canónica ausente permanece no acreditada. "
        "Este selector es independiente de los tipos documentales y de los componentes B1."
    )
    if any("Divisa" in d.get("Limitación", "") for d in result.diagnostics):
        st.warning(
            "Hay componentes con divisa incompatible: se han excluido sin convertir importes."
        )
    with st.expander("Explicación del desglose y motivos de indisponibilidad"):
        st.caption(
            "«Explicado completamente» describe la descomposición del bruto de esa extracción. "
            "No acredita salario recurrente ni explica causalmente una subida contractual. "
            "Las partidas sin correspondencia permanecen en la ficha."
        )
        if result.diagnostics:
            st.dataframe(list(result.diagnostics), hide_index=True)
