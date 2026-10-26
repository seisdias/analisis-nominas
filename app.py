"""Local, read-only canonical document explorer: streamlit run app.py."""

import streamlit as st

from src.analysis_panel import render_panel
from src.coverage_view import render_coverage
from src.document_explorer import render_app
from src.payroll_timeline import render_timeline

st.set_page_config(page_title='Análisis de Nóminas', page_icon=':material/description:',
                   layout='wide')
pages = [st.Page(render_panel, title='Panel de análisis', icon=':material/analytics:'),
         st.Page(render_app, title='Explorador', icon=':material/table_view:', default=True),
         st.Page(render_timeline, title='Evolución histórica', icon=':material/timeline:'),
         st.Page(render_coverage, title='Cobertura documental', icon=':material/folder:')]
page = st.navigation(pages, position='hidden')
with st.sidebar:
    st.subheader('Análisis de Nóminas')
    st.caption('Archivo documental')
    for item in pages:
        st.page_link(item, width='stretch')
    st.caption('Consulta en solo lectura')
page.run()
