"""Read-only analytical interpretation within one selected extraction."""

from decimal import Decimal

import streamlit as st

from src.breakdown_completeness import diagnose_breakdown
from src.canonical.values import ExactDecimal, ValueState
from src.document_concepts import REFERENCE_FIELDS, ExtractionConcepts
from src.economic_classification import Function, Knowledge, classify_extraction


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
    report = diagnose_breakdown(extraction)
    diagnostics = report.diagnostics

    def number(value: Decimal | None) -> str:
        return format(value, "f").replace(".", ",") if value is not None else "Sin cálculo"

    st.dataframe(
        [
            {
                "Comprobación": d.magnitude,
                "Estado de completitud": report.completeness[index].state.value
                if index < 2 else "Requiere ambas secciones y relación bruto/neto",
                "Contrato": d.contract_reference.split(":", 1)[0]
                if d.contract_reference else "Sin contrato aplicable",
                "Total de componentes": number(d.calculated),
                "Total documental": number(d.target.fact.value.value.to_decimal())
                if d.target and d.target.fact.value.state == ValueState.PRESENT
                and isinstance(d.target.fact.value.value, ExactDecimal) else "No disponible",
                "Diagnóstico": d.status.value,
                "Diferencia no explicada": format(d.difference, "f").replace(".", ",")
                if d.difference is not None
                else "Sin cálculo",
                "Naturaleza del resultado": d.knowledge.value,
                "Limitación": d.reason,
            }
            for index, d in enumerate(diagnostics)
        ],
        hide_index=True,
    )
    st.caption(
        "Conciliado aritméticamente no equivale a certificado económicamente. "
        "Cobertura de filas no acredita completitud. Las secciones se evalúan por separado. "
        "Se usa la unidad monetaria local de la tabla, sin inferir EUR cuando falta la divisa. "
        "Una diferencia permanece sin explicar; no se atribuye a bonus o salario fijo."
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
                    "Documento": d.document_id,
                    "Contrato y justificación": d.contract_reference or "No acreditado",
                    "Hecho total": d.target.fact.fact_id if d.target else "No disponible",
                }
                for d in diagnostics
            ],
            hide_index=True,
        )

        st.dataframe(
            [{"Sección": c.section.value, "Estado": c.state.value,
              "Factores de rechazo": ", ".join(c.reasons) or "Ninguno",
              "Ocurrencias no participantes": ", ".join(c.excluded)}
             for c in report.completeness], hide_index=True,
        )
        participants = [
            {"Sección": d.magnitude, "Hecho participante": f.fact.fact_id,
             "Clave": f.fact.fact_key, "Extracción": f.fact.extraction_id,
             "Páginas conocidas": ", ".join(map(str, f.pages)) or "Sin página exacta"}
            for d in diagnostics for f in d.participants
        ]
        if participants:
            st.dataframe(participants, hide_index=True)
