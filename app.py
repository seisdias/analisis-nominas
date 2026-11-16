"""Local read-only payroll analysis and documentary inspection."""
import streamlit as st

from src.analysis_panel import render_documents, render_panel

st.set_page_config(page_title='Análisis de Nóminas', page_icon=':material/description:',
                   layout='wide')
pages = [st.Page(render_panel, title='Análisis', icon=':material/analytics:', default=True),
         st.Page(render_documents, title='Documentos', icon=':material/folder:')]
st.navigation(pages, position='sidebar').run()
