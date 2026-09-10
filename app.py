# -*- coding: utf-8 -*-
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.models.nomina import Nomina
from src.services.database_service import DatabaseService
from src.services.ingestion_service import parse_nomina_pdf

st.set_page_config(page_title="Gestión de Nóminas y Parseador PDF", layout="wide")

DB_PATH = os.environ.get("ANALISIS_NOMINAS_DB", "data/runtime/nominas.sqlite")
database = DatabaseService(DB_PATH)
database.init_db()


def load_data():
    rows = database.obtener_todos()
    if not rows:
        return pd.DataFrame(columns=["id", "periodo", "empresa", "total_devengado",
                                     "liquido_percibir", "irpf_porcentaje"])
    return pd.DataFrame(rows).sort_values("periodo")


def get_existing_ids():
    return {row["id"] for row in database.obtener_todos()}


def insert_or_replace_nomina(data):
    # Duplicates are rejected; replacements must not silently delete data.
    database.guardar_documento(Nomina.from_dict(data))


def delete_nomina(nomina_id):
    database.eliminar_documento(nomina_id)


# Carga en vivo
df = load_data()

# ==========================================
# SIDEBAR: Selector y Parseador Masivo
# ==========================================
st.sidebar.header("📁 Parseador Masivo de PDF")

uploaded_files = st.sidebar.file_uploader(
    "Selecciona uno o más ficheros PDF",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    if st.sidebar.button("⚙️ Procesar Archivos"):
        existing_ids = get_existing_ids()
        totales = len(uploaded_files)
        cargados = 0
        erroneos = 0
        existentes_conflictos = []

        for idx, file in enumerate(uploaded_files):
            try:
                file.seek(0)
                parsed_data = parse_nomina_pdf(file, filename=file.name).to_dict()

                if not parsed_data or "id" not in parsed_data:
                    erroneos += 1
                    continue

                nomina_id = parsed_data["id"]

                if nomina_id in existing_ids:
                    existentes_conflictos.append({"idx": idx, "filename": file.name, "data": parsed_data})
                else:
                    insert_or_replace_nomina(parsed_data)
                    cargados += 1
                    existing_ids.add(nomina_id)
            except Exception as e:
                st.sidebar.error(f"Error en {file.name}: {e}")
                erroneos += 1

        st.session_state.summary = {
            "totales": totales,
            "cargados": cargados,
            "erroneos": erroneos,
            "conflictos": len(existentes_conflictos)
        }
        st.session_state.pending_replaces = existentes_conflictos
        st.rerun()

if "summary" in st.session_state:
    s = st.session_state.summary
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Resumen del Procesamiento")
    st.sidebar.write(f"• **Archivos Totales:** {s['totales']}")
    st.sidebar.write(f"• **Cargados Éxito:** {s['cargados']}")
    st.sidebar.write(f"• **Erróneos:** {s['erroneos']}")
    st.sidebar.write(f"• **Ya Existentes:** {s['conflictos']}")

if st.session_state.get("pending_replaces"):
    st.warning("Los documentos duplicados se han omitido; no se han reemplazado registros.")

# ==========================================
# PANEL PRINCIPAL
# ==========================================
st.title("📊 Análisis y Gestión de Nóminas")
st.caption(f"Base de datos activa: `data/runtime/nominas.sqlite` | Total registros: {len(df)}")
st.markdown("---")

df_valid = df[df['total_devengado'] > 0].copy()

if not df_valid.empty:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Último Sueldo Bruto", f"{df_valid['total_devengado'].iloc[-1]:,.2f} €",
                  delta=f"{((df_valid['total_devengado'].iloc[-1] / df_valid['total_devengado'].iloc[0]) - 1) * 100:.1f}% acum.")
    with col2:
        st.metric("Último Sueldo Líquido", f"{df_valid['liquido_percibir'].iloc[-1]:,.2f} €")
    with col3:
        st.metric("Retención IRPF Actual", f"{df_valid['irpf_porcentaje'].iloc[-1]} %")
    with col4:
        st.metric("Empresas Registradas", len(df_valid["empresa"].unique()))

    st.markdown("---")

    fig_evolucion = go.Figure()
    fig_evolucion.add_trace(
        go.Scatter(x=df_valid['periodo'], y=df_valid['total_devengado'], mode='lines+markers', name='Salario Bruto (€)',
                   line=dict(color='#2E86AB', width=3)))
    fig_evolucion.add_trace(go.Scatter(x=df_valid['periodo'], y=df_valid['liquido_percibir'], mode='lines+markers',
                                       name='Líquido a Percibir (€)', line=dict(color='#A23B72', width=3)))

    fig_evolucion.update_layout(
        title="<b>Evolución Salarial Histórica (Bruto vs Líquido)</b>",
        xaxis_title="Periodo",
        yaxis_title="Euros (€)",
        hovermode="x unified",
        template="plotly_white"
    )
    st.plotly_chart(fig_evolucion, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        fig_empresa = px.box(df_valid, x="empresa", y="total_devengado", color="empresa",
                             title="<b>Rango Salarial Bruto por Empresa</b>")
        st.plotly_chart(fig_empresa, width="stretch")

    with c2:
        fig_irpf = px.bar(df_valid, x="periodo", y="irpf_porcentaje", color="empresa",
                          title="<b>Evolución del % de IRPF Retenido</b>", text_auto=True)
        st.plotly_chart(fig_irpf, width="stretch")
else:
    st.info("No hay datos salariales válidos registrados en la base de datos.")

with st.expander("📂 Registros guardados en SQLite (Gestión y Borrado)"):
    st.dataframe(df, width="stretch")

    st.subheader("🗑️ Eliminar registro por ID")
    col_del1, col_del2 = st.columns([3, 1])
    with col_del1:
        id_to_delete = st.selectbox("Selecciona ID a borrar:", df["id"].tolist())
    with col_del2:
        if st.button("❌ Eliminar Registro"):
            delete_nomina(id_to_delete)
            st.success(f"Registro {id_to_delete} eliminado.")
            st.rerun()