"""Read-only analytical interpretation within one selected extraction."""

import streamlit as st

from src.canonical.values import ValueState
from src.document_concepts import REFERENCE_FIELDS, ExtractionConcepts
from src.economic_classification import Function, Knowledge, classify_extraction
from src.salary_reconciliation import reconcile


def render_classification(extraction: ExtractionConcepts) -> None:
    classification = classify_extraction(extraction)
    st.subheader("Clasificación y conciliación económica")
    st.caption(
        "Interpretación analítica de esta extracción, sin nuevas certificaciones. "
        "Salario base identificado no significa salario mensual comparable. "
        "La repetición de una partida no acredita periodicidad contractual. "
        "Los conceptos y sus valores originales permanecen en el desglose y la trazabilidad."
    )
    rows = []
    for c in classification.concepts:
        label = c.source.get("concepto")
        amount = c.source.get("importe")
        rows.append(
            {
                "Concepto original": str(label.fact.value.value)
                if label and label.fact.value.state == ValueState.PRESENT
                else "Denominación no disponible",
                "Columna": c.nature.value,
                "Función económica": c.function.value,
                "Estado de clasificación": "Correspondencia explícita"
                if c.function != Function.UNKNOWN
                else "Sin correspondencia verificada",
                "Atraso documentado": {True: "Sí", False: "No", None: "Desconocido"}[c.arrears],
                "Periodicidad": c.periodicity.value,
                "Naturaleza del valor": Knowledge.DOCUMENTED.value
                if amount and amount.fact.value.state == ValueState.PRESENT
                else Knowledge.UNDETERMINABLE.value,
            }
        )
    if rows:
        st.dataframe(rows, hide_index=True)
    for issue in classification.issues:
        st.caption(issue)
    diagnostics = reconcile(extraction)
    st.dataframe(
        [
            {
                "Comprobación": d.magnitude,
                "Diagnóstico": d.status.value,
                "Diferencia no explicada": format(d.difference, "f").replace(".", ",")
                if d.difference is not None
                else "Sin cálculo",
                "Naturaleza del resultado": d.knowledge.value,
                "Limitación": d.reason,
            }
            for d in diagnostics
        ],
        hide_index=True,
    )
    st.caption(
        "No hay contratos de completitud y signos activados para el corpus. No se calcula un residuo "
        "ni se atribuye a bonus o salario fijo. La moneda ausente continúa sin acreditar; no se infiere EUR."
    )
    with st.expander("Funciones de referencia y contrato de conciliación"):
        if classification.references:
            st.dataframe(
                [
                    {
                        "Campo original": REFERENCE_FIELDS.get(
                            r.source.fact.fact_key.removeprefix("nomina.").removeprefix("payload/"),
                            r.source.fact.fact_key,
                        ),
                        "Naturaleza": r.nature.value,
                        "Función": r.function.value,
                        "Relación con los totales": r.relation.value,
                        "Hecho original": r.source.fact.fact_id,
                    }
                    for r in classification.references
                ],
                hide_index=True,
            )
        st.write(
            "Los campos escalares pueden repetir partidas: nunca se añaden a las filas. "
            "Conciliar requiere un contrato revisado de la revisión exacta del extractor que acredite "
            "lista completa, aditividad, signos y unidad común. Igualdad numérica no demuestra exhaustividad. "
            "Versiones y extracciones se evalúan por separado; la selección visual no modifica resoluciones."
        )
        st.dataframe(
            [
                {
                    "Magnitud": d.magnitude,
                    "Fórmula diagnóstica": d.formula,
                    "Versión": d.version_id,
                    "Extracción": d.extraction_id,
                }
                for d in diagnostics
            ],
            hide_index=True,
        )
