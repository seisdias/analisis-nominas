"""First ordinary-income comparison within the existing contextual panel."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import altair as alt
import streamlit as st

from src.analytic_dataset import AnalyticDocument
from src.canonical_inspection import InspectionError, open_inspector
from src.component_view import component_visibility
from src.document_concepts import read_document_concepts
from src.economic_components import documentary_block
from src.gui_presentation import canonical_value_text, short_id
from src.income_evolution import (
    COMPLETE,
    DISPLAY,
    GROSS,
    INDEPENDENT,
    MONTHLY,
    ORDINARY,
    SERIES,
    IncomeProjection,
    matching_periods,
    project_income,
    visible_income,
)
from src.reconstruction_view import render_salary_evidence
from src.salary_reconciliation import Status
from src.salary_reconstruction import Bucket


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
    prepared = [
        dict(
            r,
            Dato=DISPLAY[r["Componente"]],
            Empresa=r["Empresa"] + " · " + r.get("Moneda canónica", "No acreditada"),
            Alcance="Parcial"
            if r["Componente"] == ORDINARY
            else "Total"
            if r["Componente"] in (GROSS, INDEPENDENT, COMPLETE, MONTHLY)
            else "Partida",
        )
        for r in rows
    ]
    selection = alt.selection_point(name="nomina", fields=["Documento"], on="click", toggle=False)
    labels = [DISPLAY[name] for name in SERIES]
    return (
        alt.Chart(alt.Data(values=prepared))
        .mark_point(size=90, filled=True)
        .encode(
            x=alt.X("Fecha:T", title="Periodo del documento", axis=alt.Axis(format="%m/%Y")),
            y=alt.Y("Importe:Q", title="Importe (€ de presentación)", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "Dato:N",
                title=None,
                scale=alt.Scale(domain=labels, scheme="tableau10"),
                legend=alt.Legend(
                    values=[label for label in labels if any(r["Dato"] == label for r in prepared)]
                ),
            ),
            shape=alt.Shape(
                "Alcance:N",
                title="Cobertura",
                scale=alt.Scale(
                    domain=["Total", "Parcial", "Partida"], range=["square", "diamond", "circle"]
                ),
            ),
            tooltip=[
                "Periodo del documento:N",
                "Dato:N",
                "Importe exacto:N",
                "Cobertura:N",
                "Etiqueta original:N",
                "Fórmula:N",
                "Documento:N",
                "Hecho:N",
                "Versión:N",
            ],
        )
        .add_params(selection)
        .properties(height=245)
        .facet(row=alt.Row("Empresa:N", title=None))
    )


def _chart_document(key: str) -> None:
    event = st.session_state.get(key + "_chart", {})
    points = event.get("selection", {}).get("nomina", [])
    st.session_state[key + "_document"] = points[0].get("Documento") if len(points) == 1 else None


def _composition(result: IncomeProjection, rows: list[dict[str, Any]], key: str) -> None:
    totals = {r["Documento"]: r for r in result.rows if r["Componente"] in (GROSS, INDEPENDENT)}
    documents = {r["Documento"]: r for r in rows}
    if not documents:
        return
    picker = key + "_document"
    if st.session_state.get(picker) not in documents:
        st.session_state[picker] = None
    identity = st.selectbox(
        "Ver composición de una nómina",
        list(documents),
        index=None,
        key=picker,
        placeholder="Pulsa un punto o elige una nómina",
        format_func=lambda i: f"{documents[i]['Periodo del documento']} · {documents[i]['Empresa']} · {short_id(i)}",
    )
    if identity is None:
        return
    gross = totals.get(identity)
    if gross:
        with st.container(horizontal=True):
            st.metric(DISPLAY[gross["Componente"]], gross["Importe exacto"])
            for row in result.rows:
                if row["Documento"] == identity and row["Componente"] in (
                    ORDINARY,
                    COMPLETE,
                    MONTHLY,
                ):
                    st.metric(DISPLAY[row["Componente"]], row["Importe exacto"])
    salary = result.salary_evidence.get(identity)
    if salary is not None:
        render_salary_evidence(salary)
    report = result.compositions.get(identity)
    diagnosis = next((d for d in result.diagnostics if d["Documento"] == identity), {})
    if report is None:
        if gross and gross["Componente"] == INDEPENDENT:
            st.caption("El importe corresponde al documento de paga extraordinaria independiente.")
        else:
            st.info(
                "Desglose del bruto no evaluable. "
                + diagnosis.get("Limitación", "Falta un desglose vinculado a este total.")
            )
        individual = [
            {
                "Partida del documento": row["Etiqueta original"],
                "Grupo": DISPLAY[row["Componente"]],
                "Importe documental": row["Importe exacto"],
            }
            for row in result.rows
            if row["Documento"] == identity and "Ocurrencia" in row
        ]
        if individual:
            st.caption(
                "Partidas disponibles para inspección individual. Su participación en el total queda pendiente."
            )
            st.dataframe(individual, hide_index=True)
        return
    st.write(diagnosis.get("Explicación", "") + " · " + report.earnings.status.value)
    if report.earnings.status == Status.DIFFERENCE:
        st.write(
            "Diferencia no explicada (partidas menos bruto): "
            + str(report.earnings.difference).replace(".", ",")
        )
    groups = {
        Bucket.FIXED_CANDIDATE: "Salario base o complemento documentado",
        Bucket.EXTRA: DISPLAY["Extras identificadas"],
        Bucket.UNKNOWN: "Sin clasificación suficiente",
    }
    items = []
    for part in report.parts:
        occurrence = part.source.source
        label, amount = occurrence.get("concepto"), occurrence.get("importe")
        items.append(
            {
                "Partida del documento": canonical_value_text(label.fact.value)
                if label
                else "Denominación desconocida",
                "Grupo": groups.get(part.bucket, part.bucket.value),
                "Importe documental": canonical_value_text(amount.fact.value, monetary=True)
                if amount
                else "No extraído",
            }
        )
    if items:
        st.dataframe(items, hide_index=True)
    if diagnosis.get("Conceptos pendientes", "0") != "0":
        st.caption("Las partidas pendientes conservan su importe o estado documental.")
    if report.earnings.status != Status.RECONCILED:
        st.caption(report.earnings.reason)


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
        "El rombo muestra la suma de partidas ordinarias identificadas. Su cobertura es parcial. "
        "El cuadrado muestra el total y los círculos, las partidas. "
        "Selecciona un punto para consultar su composición."
    )
    try:
        result = load_income(database, documents, restrictions, totals)
    except InspectionError:
        st.error("No se pudo consultar la evolución retributiva en solo lectura.")
        return
    if result.rows:
        selection = component_visibility(
            {r["Componente"] for r in result.rows},
            key=key,
            options=SERIES,
            label="Datos a analizar",
            format_func=DISPLAY.__getitem__,
            reset_label="Restablecer series",
        )
        rows = visible_income(result.rows, selection)
        if rows and show_chart and any(r["Componente"] != GROSS for r in result.rows):
            st.altair_chart(
                income_chart(rows),
                width="stretch",
                key=key + "_chart",
                on_select=lambda: _chart_document(key),
                selection_mode="nomina",
            )
        elif rows:
            st.dataframe(
                [
                    {
                        "Periodo": r["Periodo del documento"],
                        "Empresa": r["Empresa"],
                        "Dato": DISPLAY[r["Componente"]],
                        "Importe": r["Importe exacto"],
                    }
                    for r in rows
                ],
                hide_index=True,
            )
        else:
            st.info("Series ocultas; la cobertura documental y los filtros permanecen intactos.")
        _composition(result, rows, key)
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
    if not any(row["Componente"] == MONTHLY for row in result.rows):
        st.caption(
            "Fijo mensual comparable no disponible. Falta acreditar la cobertura del sueldo fijo, "
            "su periodicidad y la composición anual de las pagas."
        )
    st.caption(
        "Periodo de la nómina · euros de presentación. Cada panel separa empresa y moneda documentada."
    )
    if result.salary_evidence:
        with st.expander("Qué falta para acreditar el fijo en este contexto"):
            st.caption(
                "Evaluación por documento, antes de ocultar series. Los tramos de partidas coincidentes "
                "son documentales, no regímenes salariales acreditados. Abre una nómina para ver "
                "los hechos y la documentación necesaria."
            )
            labels = {row["Documento"]: row for row in result.rows}
            st.dataframe(
                [
                    {
                        "Periodo": labels[identity]["Periodo del documento"],
                        "Empresa": labels[identity]["Empresa"],
                        **{
                            q.label: "Acreditado en su ámbito" if q.satisfied else "Pendiente"
                            for q in report.requirements
                        },
                    }
                    for identity, report in sorted(
                        result.salary_evidence.items(),
                        key=lambda pair: (pair[1].reconstruction.period or (0, 0), pair[0]),
                    )
                ],
                hide_index=True,
            )
    if result.bases:
        with st.expander("Meses con las mismas partidas ordinarias"):
            st.caption(
                "Periodos consecutivos con mes documental completo, mismos conceptos y mismo formato. "
                "La comparación se limita a las partidas identificadas. La moneda pendiente figura en la tabla."
            )
            windows = matching_periods(result.bases)
            if windows:
                st.dataframe(windows, hide_index=True)
            else:
                st.write("No hay dos meses consecutivos con esta cobertura en el periodo elegido.")
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
