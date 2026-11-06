"""Compact read-only remuneration explanation for one explicitly viewed extraction."""

import streamlit as st

from src.document_concepts import ExtractionConcepts
from src.gui_presentation import canonical_value_text
from src.salary_evidence import SalaryEvidence, describe_salary, evidence_rows
from src.salary_reconstruction import identified_ordinary, reconstruct


def render_reconstruction(extraction: ExtractionConcepts) -> None:
    r = reconstruct(extraction)
    st.subheader("Reconstrucción retributiva")
    st.caption(
        "Componentes identificados, no salario fijo total reconstruido. "
        "Los bonus y atrasos no se incorporan al fijo. No son pagos adicionales al bruto. "
        "Diagnóstico exclusivo de esta versión y extracción; no consolida versiones."
    )
    if r.parts:
        st.dataframe(
            [
                {
                    "Concepto": canonical_value_text(label.fact.value)
                    if (label := p.source.source.get("concepto"))
                    else "Sin denominación",
                    "Grupo retributivo": p.bucket.value,
                    "Importe documental": canonical_value_text(amount.fact.value)
                    if (amount := p.source.source.get("importe"))
                    else "No extraído",
                    "Tipo de resultado": "Documentado"
                    if p.amount is not None
                    else "No determinable",
                }
                for p in r.parts
            ],
            hide_index=True,
            column_config={"Importe documental": st.column_config.TextColumn(alignment="right")},
        )
    else:
        st.info(
            "Sin devengos estructurados utilizables. No se reconstruyen componentes por diferencias entre totales."
        )
    if r.independent_extras:
        st.caption(
            "Paga extraordinaria independiente documentada: el total se conserva como referencia, "
            "no se añade a sus posibles filas ni se extrapola a una mensualidad."
        )
        st.dataframe(
            [
                {
                    "Referencia": "Total de extra independiente",
                    "Valor documental": canonical_value_text(f.fact.value),
                }
                for f in r.independent_extras
            ],
            hide_index=True,
        )
    ordinary = identified_ordinary(extraction)
    indicators = (ordinary, r.fixed, r.monthly, r.annual)
    available = [i for i in indicators if i.amount is not None]
    if available:
        st.dataframe(
            [
                {
                    "Magnitud": i.label,
                    "Importe de presentación": i.amount.display() if i.amount else "",
                    "Cobertura": i.coverage.value,
                    "Resultado": i.knowledge.value,
                }
                for i in available
            ],
            hide_index=True,
        )
    if extraction.extractor_name in ("InecoParser", "ExcelticParser"):
        render_salary_evidence(describe_salary(extraction, r, ordinary))
    elif r.fixed.amount is None:
        st.info(
            "No hay cobertura contractual del fijo ni periodicidad suficientes para calcular "
            "un salario fijo completo o equivalentes mensual/anual. Las partidas identificadas siguen disponibles."
        )
    st.caption(
        "Modalidad: " + r.payment_mode.value + ". La unidad canónica permanece sin inferir; "
        "la convención visual EUR no acredita moneda. No se deduce fecha de pago ni devengo del periodo documental."
    )
    with st.expander("Cobertura, fórmulas y evidencia de la reconstrucción"):
        st.dataframe(
            [
                {
                    "Magnitud": i.label,
                    "Cobertura": i.coverage.value,
                    "Tipo": i.knowledge.value,
                    "Fórmula": i.formula or "Sin cálculo",
                    "Motivo": i.reason,
                    "Contrato": "; ".join(i.evidence) or "Sin contrato retributivo aplicable",
                }
                for i in indicators
            ],
            hide_index=True,
        )
        st.write("Conciliación de devengos: " + r.earnings.status.value + ". " + r.earnings.reason)
        if r.earnings.difference is not None and r.earnings.difference != 0:
            st.write(
                "Diferencia no explicada: " + format(r.earnings.difference, "f").replace(".", ",")
            )
        st.caption(
            "Cobertura aritmética no acredita recurrencia salarial. "
            "No se suman escalares con filas, ni se mezclan versiones. "
            "Una equivalencia anual describe una estructura vigente, no ingresos cobrados en el año."
        )
        for issue in r.issues:
            st.caption(issue)
        if r.parts:
            st.dataframe(
                [
                    {
                        "Documento": r.scope.document_id,
                        "Versión": r.scope.version_id,
                        "Extracción": r.scope.extraction_id,
                        "Ocurrencia": p.source.source.occurrence,
                        "Hecho": f.fact.fact_id,
                        "Clave": f.fact.fact_key,
                        "Página": ", ".join(map(str, f.pages)) or "No registrada",
                        "Estado": f.fact.value.state.value,
                        "Moneda canónica": f.fact.value.currency.code
                        if f.fact.value.currency
                        else "No acreditada",
                        "Contrato de clasificación": p.source.contract,
                        "Periodo documental": f"{r.period[1]:02d}/{r.period[0]}"
                        if r.period
                        else "Desconocido",
                    }
                    for p in r.parts
                    if (f := p.source.source.get("importe")) is not None
                ],
                hide_index=True,
            )


def render_salary_evidence(report: SalaryEvidence) -> None:
    with st.expander("Qué falta para acreditar el fijo"):
        st.caption(
            "Cada requisito tiene un alcance distinto. Un mes civil completo y unos devengos "
            "conciliados no prueban la recurrencia de los complementos ni el régimen anual. "
            "Las partidas ordinarias identificadas siguen siendo parciales."
        )
        st.dataframe(evidence_rows(report), hide_index=True)
        st.caption(
            "Para comparar 12 y 14 pagas hacen falta contratos de cobertura, modalidad y extras. "
            "Una diferencia entre parciales no se presenta como subida salarial."
        )
        with st.expander("Hechos que sustentan los requisitos"):
            st.dataframe(
                [
                    {
                        "Requisito": q.label,
                        "Documento": report.reconstruction.scope.document_id,
                        "Versión": report.reconstruction.scope.version_id,
                        "Extracción": report.reconstruction.scope.extraction_id,
                        "Hecho": f.fact.fact_id,
                        "Clave": f.fact.fact_key,
                        "Estado": f.fact.value.state.value,
                        "Página": ", ".join(map(str, f.pages)) or "No registrada",
                    }
                    for q in report.requirements
                    for f in q.facts
                ],
                hide_index=True,
            )
