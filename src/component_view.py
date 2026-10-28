"""Shared component visualization for panel and history; no documentary cache."""
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import altair as alt
import streamlit as st

from src.analytic_dataset import AnalyticDocument
from src.canonical_inspection import InspectionError, open_inspector
from src.document_concepts import read_document_concepts
from src.economic_components import (
    COMPONENTS,
    ComponentPoint,
    ComponentProjection,
    component_rows,
    documentary_block,
    project_components,
)
from src.gui_presentation import short_id

TOTALS_DESCRIPTION = 'Bruto/neto del documento, incluidos posibles conceptos extraordinarios'


def load_components(database: Path, documents: Sequence[AnalyticDocument],
                    blocked: Mapping[str, str]) -> ComponentProjection:
    with open_inspector(database) as inspector:
        sources = {d.document_id: read_document_concepts(inspector, d.document_id)
                   for d in documents if documentary_block(d, blocked) is None}
    return project_components(documents, sources, blocked)


def component_restrictions(table: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Reuse full-context timeline decisions, not category/series-filtered rows."""
    return {r['Documento']: r['Representación'] for r in table
            if r['Representación'] not in ('Representado', 'Sin importe certificado')}


def visibility_subset(points: Sequence[ComponentPoint], selected: Sequence[str]) -> tuple[ComponentPoint, ...]:
    return tuple(p for p in points if p.component in selected)


def _remember(key: str, available: tuple[str, ...]) -> None:
    hidden = set(st.session_state.get(key + '_hidden', ())) - set(available)
    hidden.update(set(available) - set(st.session_state.get(key, ())))
    st.session_state[key + '_hidden'] = tuple(sorted(hidden))


def _reset(key: str) -> None:
    st.session_state.pop(key, None)
    st.session_state.pop(key + '_hidden', None)


def component_visibility(available: set[str], *, key: str) -> tuple[str, ...]:
    options = tuple(c for c in COMPONENTS if c in available)
    hidden = set(st.session_state.get(key + '_hidden', ()))
    st.session_state[key] = [c for c in options if c not in hidden]
    selected = st.multiselect('Componentes económicos visibles', options, key=key,
        persist_state='session', on_change=_remember, args=(key, options))
    st.button('Restablecer componentes', key=key + '_reset', on_click=_reset, args=(key,))
    return tuple(c for c in selected if c in options)


def component_chart(rows: list[dict[str, Any]]) -> alt.Chart | alt.FacetChart:
    chart = alt.Chart(alt.Data(values=rows)).mark_point(filled=True, size=90).encode(
        x=alt.X('Fecha:T', title='Periodo del documento', axis=alt.Axis(format='%m/%Y')),
        y=alt.Y('Importe:Q', title='Importe documental (€ de presentación)', scale=alt.Scale(zero=False)),
        color=alt.Color('Componente:N', scale=alt.Scale(domain=list(COMPONENTS),
            range=['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00']),
            legend=alt.Legend(values=[c for c in COMPONENTS if any(r['Componente'] == c for r in rows)])),
        tooltip=['Periodo del documento:N','Empresa:N','Componente:N','Etiqueta original:N',
                 'Código original:N','Columna documental:N','Importe exacto:N','Moneda canónica:N',
                 'Estado:N','Documento:N','Versión:N','Extracción:N','Ocurrencia:N','Hecho:N',
                 'Clave original:N','Páginas:N'],
    ).properties(height=260).interactive()
    if len({r['Empresa'] for r in rows}) > 1:
        return chart.facet(row=alt.Row('Empresa:N', title=None))
    return chart


def render_components(database: Path, documents: Sequence[AnalyticDocument],
                      restrictions: Mapping[str, str], *, key: str) -> None:
    st.subheader('Componentes extraordinarios documentados')
    st.caption('Partidas internas, no pagos adicionales al bruto ni observaciones certificadas. '
               'No se calcula neto de componentes. El eje usa el periodo del documento, no devengo ni cobro. '
               'EUR es una convención visual: la moneda ausente no queda acreditada. '
               'Los marcadores no suman partidas ni unen meses.')
    try:
        result = load_components(database, documents, restrictions)
    except InspectionError:
        st.error('No se pudo consultar el desglose en solo lectura. Los totales y filtros no se modifican.')
        return
    if result.points:
        selected = component_visibility({p.component for p in result.points}, key=key)
        rows = component_rows(visibility_subset(result.points, selected))
        st.caption('Control independiente de «Tipos de ingreso»: no cambia cobertura, totales, medias ni ficha.')
        if rows:
            st.altair_chart(component_chart(rows), width='stretch')
            st.caption(f'{len(rows)} ocurrencias individuales visibles, sin agregación. '
                       'Puntos coincidentes pueden solaparse; la trazabilidad conserva cada ocurrencia.')
            with st.expander('Trazabilidad de los componentes visibles'):
                st.dataframe([{k:v for k,v in r.items() if k not in ('Fecha','Importe')}
                              for r in rows], hide_index=True)
        else:
            st.info('Todos los componentes están ocultos. La documentación del contexto permanece intacta.')
    else:
        st.info('No hay componentes representables en este contexto. Consulta los conceptos y escalares '
                'en la ficha. Sin desglose persistido no se reconstruyen partidas a partir de los totales.')
    if any('divisa' in reason.lower() for _, reason in result.omitted):
        st.warning('Hay una divisa explícita incompatible con EUR. Esos componentes no se convierten ni se representan.')
    if result.omitted:
        with st.expander('Disponibilidad y límites de los componentes'):
            st.caption('Los totales conservan sus contratos propios. La selección de versión en la ficha '
                       'no autoriza series multiversión: quedan pendientes de D.2.3-C. '
                       'Las correspondencias no cubiertas siguen disponibles en el visor documental.')
            st.dataframe([{'Documento': short_id(i), 'Motivo': reason} for i,reason in result.omitted], hide_index=True)
