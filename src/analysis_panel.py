"""Contextual Streamlit presentation over existing read-only contracts."""
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import streamlit as st

from src.analysis_context import AnalysisContext, ContextFilters, build_context, parse_period
from src.analytic_dataset import read_analytic_dataset
from src.annual_view import render_annual
from src.canonical.values import CanonicalValue, ValueState
from src.canonical_inspection import InspectionError, open_inspector
from src.cli_config import ConfigurationError, load_config
from src.component_view import component_restrictions, render_components
from src.concepts_view import render_concepts
from src.coverage_view import CATEGORIES, REASONS, _details, render_coverage
from src.document_explorer import format_amount, render_app
from src.documentary_coverage import Availability, CoverageDocument
from src.gui_presentation import (
    canonical_value_text,
    format_period,
    short_id,
)
from src.income_evolution import DISPLAY, GROSS, INDEPENDENT
from src.income_view import income_chart, load_income, render_income
from src.payroll_timeline import Timeline, classified_timeline, reset_categories


@dataclass(frozen=True)
class PanelSnapshot:
    coverage: tuple[CoverageDocument, ...]
    documents: dict[str, dict[str, Any]]
    timeline: list[dict[str, Any]]


def load_panel(database: Path, withheld: tuple[str, ...] = ()) -> PanelSnapshot:
    """One verified snapshot per rerun, never a cache or a second certification path."""
    with open_inspector(database) as inspector:
        rows = {r['document_id']: r for r in inspector.documents()}
        dataset = read_analytic_dataset(inspector)
        if set(rows) != {d.document_id for d in dataset}:
            raise InspectionError('Inconsistent panel snapshot')
        coverage = tuple(CoverageDocument(d, rows[d.document_id]['company_text'],
            rows[d.document_id]['year'], rows[d.document_id]['month'],
            Availability(rows[d.document_id]['gross']['status']),
            Availability(rows[d.document_id]['net']['status']), d.document_id in withheld) for d in dataset)
        return PanelSnapshot(coverage, rows, inspector.timeline_records())


def context_timeline(snapshot: PanelSnapshot, context: AnalysisContext, filters: ContextFilters,
                     withheld: tuple[str, ...] = ()) -> Timeline:
    years = (filters.period[0][0], filters.period[1][0]) if filters.period else (1, 9999)
    # Evaluate rivals and local holds before any document selection can hide them.
    result = classified_timeline(snapshot.timeline, [d.document for d in snapshot.coverage],
        years=years, company=filters.company, withheld_document_ids=frozenset(withheld))
    ids = {d.document_id for d in context.documents}
    return type(result)([p for p in result.points if p['Documento'] in ids],
                        [r for r in result.table if r['Documento'] in ids], result.ambiguous_periods)


def _clear_document() -> None:
    st.session_state['panel_document'] = None
    for key in list(st.session_state):
        if str(key).startswith(('panel_table_', 'panel_chart_')):
            st.session_state.pop(key, None)


def _reset() -> None:
    reset_categories('panel_categories')
    for key in ('panel_company', 'panel_period', 'panel_incomplete', 'panel_document', 'panel_average', 'panel_open'):
        st.session_state.pop(key, None)


def _document_rows(snapshot: PanelSnapshot, context: AnalysisContext) -> list[dict[str, Any]]:
    return [{'Periodo': format_period(d.year, d.month), 'Empresa': d.company or 'Empresa desconocida',
             'Categoría': CATEGORIES[d.document.category],
             'Bruto': format_amount(snapshot.documents[d.document_id]['gross']),
             'Neto': format_amount(snapshot.documents[d.document_id]['net']),
             'Versiones': len(d.document.provenance),
             'Revisión': '; '.join(REASONS[r] for r in d.review_reasons) or 'Sin incidencias detectadas',
             'Restricción local': 'Sí' if d.presentation_restricted else 'No',
             'Documento': short_id(d.document_id)} for d in context.documents]



def _detail(database: Path, record: CoverageDocument, snapshot: PanelSnapshot) -> None:
    st.subheader('Ficha documental')
    st.write(f'{record.company or "Empresa desconocida"} · {format_period(record.year, record.month)}')
    st.write(CATEGORIES[record.document.category] + ' · Tipo original: ' + record.document.original_document_type)
    row = snapshot.documents[record.document_id]
    st.dataframe([{'Bruto documental': format_amount(row['gross']), 'Neto documental': format_amount(row['net'])}],
                 hide_index=True, column_config={name: st.column_config.TextColumn(alignment='right')
                 for name in ('Bruto documental', 'Neto documental')})
    st.caption('Los estados de los importes proceden del inspector. Certificado no significa sumable. '
               'EUR es el ámbito de presentación, no evidencia de moneda económica.')
    if record.review_reasons:
        st.warning('; '.join(REASONS[r] for r in record.review_reasons))
    if len(record.document.provenance) > 1:
        st.info('Documento multiversión: se conservan todas las versiones; esta ficha no elige ninguna.')
    render_concepts(database, record.document_id)
    st.subheader('Contexto económico documentado')
    observations = record.document.observations
    if not observations:
        st.info('Sin observaciones económicas. No se infieren moneda, devengo ni fecha de cobro.')
    else:
        st.dataframe([{'Observación': short_id(o.observation_id), 'Magnitud original': o.magnitude,
            'Moneda registrada': o.value.currency.code if o.value.currency else 'Desconocida',
            'Empresa canónica': record.document.employer_id or 'Desconocida', 'Liquidación': canonical_value_text(o.liquidation_period),
            'Devengo': (f'{o.accrual.start} – {o.accrual.end}' if o.accrual.state == ValueState.PRESENT else canonical_value_text(CanonicalValue(state=o.accrual.state, reason_code=o.accrual.reason_code))), 'Fecha de cobro': canonical_value_text(o.payment_date),
            'Elegibilidad': str(o.eligibility)} for o in observations], hide_index=True)
    with st.expander('Trazabilidad: versiones, páginas, extracciones y soporte'):
        _details(record)


def _summary(context: AnalysisContext, filters: ContextFilters) -> None:
    report = context.report
    with st.container(horizontal=True):
        st.metric('Documentos lógicos', len(context.documents))
        st.metric('Meses documentados', len(context.months))
        st.metric('Bruto y neto certificados', len(report.certified_both))
        if filters.period and context.level != 'document':
            st.metric('Meses sin documentación localizada', len(context.missing_months))
    if context.months:
        st.caption('Periodo documental observado: ' + format_period(*context.months[0]) + ' – '
                   + format_period(*context.months[-1]) + '. No equivale a duración contractual.')
    if filters.period and context.level != 'document':
        with st.expander('Meses cubiertos y huecos'):
            st.write('Documentados: ' + (', '.join(format_period(*m) for m in context.months) or 'Ninguno'))
            st.write('Sin documentación localizada: ' + (', '.join(format_period(*m) for m in context.missing_months) or 'Ninguno'))
            st.caption('La ausencia es incierta por contexto incompleto.' if context.gaps_uncertain else
                       'Ausencia documental dentro de esta ventana; no implica desempleo ni salario cero.')
    else:
        st.caption('Para contar huecos, indica una ventana temporal explícita en Periodo.')
    if report.multiversion_ids or report.review_ids or report.restricted_ids:
        st.info(f'{len(report.multiversion_ids)} documentos multiversión · {len(report.review_ids)} con incidencias '
                f'· {len(report.restricted_ids)} con restricción local. Multiversión no implica conflicto sin resolver.')
    st.subheader('Documentación del contexto')
    counts = Counter((d.company or 'Empresa desconocida', str(d.year) if d.year else 'Año desconocido') for d in context.documents)
    st.dataframe([{'Empresa documental': company, 'Año': year, 'Documentos': count}
                  for (company, year), count in sorted(counts.items())], hide_index=True)
    st.dataframe([{'Categoría': CATEGORIES[c], 'Documentos': len(ids)} for c, ids in report.categories if ids], hide_index=True)


def _economic_rows(snapshot: PanelSnapshot, context: AnalysisContext) -> list[dict[str, Any]]:
    """Original individual totals; unknown values are never zero or reconstructed."""
    def amount(value: dict[str, Any]) -> str:
        return format_amount(value) if value['status'] == 'certified' else '—'

    return [{'Periodo': format_period(d.year, d.month),
             'Empresa': d.company or 'No disponible',
             'Tipo de nómina': CATEGORIES[d.document.category],
             'Bruto': amount(snapshot.documents[d.document_id]['gross']),
             'Neto': amount(snapshot.documents[d.document_id]['net'])}
            for d in context.documents]


def _open_document(identity: str) -> None:
    st.session_state['panel_document'] = identity
    st.switch_page(st.Page(render_documents))


def render_panel() -> None:
    st.title('Análisis de Nóminas')
    st.caption('Evolución y composición de tu retribución')
    try:
        config = load_config()
        snapshot = load_panel(config.database, config.withheld_document_ids)
    except (ConfigurationError, InspectionError):
        st.error('No se pudo abrir la base configurada en solo lectura. Revisa la configuración y el acceso.')
        return
    with st.container(border=True):
        left, right = st.columns(2)
        company = left.selectbox('Empresa', [None, *sorted({d.company for d in snapshot.coverage if d.company is not None})],
            format_func=lambda x: x if x is not None else 'Todas las empresas', key='panel_company', persist_state='session')
        text = right.text_input('Periodo', placeholder='Todo el histórico · Ej.: 2015 o 03/2015 – 09/2015',
            help='Vacío: histórico completo. Año: 2015. Mes: 09/2022. Intervalo inclusivo: 01/2015 – 06/2016.',
            key='panel_period', persist_state='session')
        st.button('Restablecer filtros', key='panel_reset', on_click=_reset)
        with st.expander('Opciones avanzadas'):
            incomplete = st.checkbox('Solo documentos con empresa o periodo incompleto', key='panel_incomplete', persist_state='session')
    try:
        period = parse_period(text)
    except ValueError as error:
        st.warning(str(error))
        return
    filters = ContextFilters(company, period, incomplete)
    context = build_context(snapshot.coverage, filters)
    by_id = {d.document_id: d for d in context.documents}
    st.session_state['panel_valid_ids'] = tuple(by_id)
    selection_key = sha256(repr((filters, tuple(by_id))).encode()).hexdigest()
    if st.session_state.get('panel_document') and st.session_state['panel_document'] not in by_id:
        _clear_document()
    if not context.documents:
        st.info('No hay coincidencias con los filtros activos. Retira un filtro o usa «Restablecer filtros».')
        return
    timeline = context_timeline(snapshot, context, filters, config.withheld_document_ids)
    income_rows: list[dict[str, Any]] = []
    st.subheader('Evolución de la retribución')
    st.caption('Cuadrados: totales de la nómina; rombos: partidas ordinarias identificadas (parciales); '
               'círculos: conceptos individuales. No son pagos adicionales al total. '
               'Importes en euros de presentación; los datos ausentes no se sustituyen por cero.')
    try:
        income = load_income(config.database, [d.document for d in context.documents],
                             component_restrictions(timeline.table), timeline.points)
        income_rows = income.rows
        if income.rows:
            chart_event = st.altair_chart(income_chart(income.rows, technical=False), width='stretch',
                key='panel_chart_' + selection_key, on_select='rerun', selection_mode='nomina')
            points = chart_event.get('selection', {}).get('nomina', [])
            if len(points) == 1 and points[0].get('Documento') in by_id:
                _open_document(points[0]['Documento'])
        else:
            st.info('No hay importes representables en la gráfica para esta selección.')
        if income.diagnostics or any(r['Representación'] != 'Representado' for r in timeline.table):
            st.caption('Algunos importes o desgloses pueden no estar disponibles. Consulta los motivos en Documentos.')
    except InspectionError:
        st.error('No se pudo consultar la evolución retributiva. La tabla conserva los importes originales.')
    st.subheader('Nóminas')
    rows = _economic_rows(snapshot, context)
    for component in dict.fromkeys(r['Componente'] for r in income_rows if r['Componente'] not in (GROSS, INDEPENDENT)):
        for identity, row in zip(by_id, rows, strict=True):
            row[DISPLAY[component]] = '; '.join(r['Importe exacto'] for r in income_rows
                if r['Documento'] == identity and r['Componente'] == component) or '—'
    st.caption('Importes originales por nómina. Selecciona una fila para abrir su ficha en Documentos.')
    event = st.dataframe(rows, hide_index=True, width='stretch', on_select='rerun',
        selection_mode='single-row', key='panel_table_' + selection_key,
        column_config={name: st.column_config.TextColumn(alignment='right') for name in ('Bruto', 'Neto')})
    if event.selection.rows:
        _open_document(tuple(by_id)[event.selection.rows[0]])
    # Accessible alternative to row selection; labels never expose internal identities.
    selected = st.selectbox('Consultar nómina', [None, *by_id],
        format_func=lambda i: 'Selecciona una nómina' if i is None else
        f'{tuple(by_id).index(i) + 1}. {by_id[i].company or "Empresa desconocida"} · '
        f'{format_period(by_id[i].year, by_id[i].month)} · {CATEGORIES[by_id[i].document.category]}',
        key='panel_open', index=None, placeholder='Selecciona una nómina')
    if selected and st.button('Abrir nómina', key='panel_open_button'):
        _open_document(selected)


def render_documents() -> None:
    """Existing explorer and coverage, with the detail selected from Analysis."""
    st.title('Documentos')
    if st.button('Volver a Análisis', key='panel_back'):
        _clear_document()
        st.switch_page(st.Page(render_panel))
    selected = st.session_state.get('panel_document')
    if selected:
        try:
            config = load_config()
            snapshot = load_panel(config.database, config.withheld_document_ids)
            record = next((d for d in snapshot.coverage if d.document_id == selected), None)
            if record is not None:
                _detail(config.database, record, snapshot)
            else:
                st.warning('La nómina seleccionada ya no está disponible.')
        except (ConfigurationError, InspectionError):
            st.error('No se pudo consultar la nómina seleccionada.')
    render_app(show_title=False)
    with st.expander('Cobertura documental', key='documents_coverage', on_change='rerun') as coverage:
        if coverage.open:
            render_coverage()
    with st.expander('Informes y evidencia económica'):
        if st.checkbox('Mostrar informes del contexto de Análisis', key='document_reports'):
            try:
                config = load_config()
                snapshot = load_panel(config.database, config.withheld_document_ids)
                filters = ContextFilters(st.session_state.get('panel_company'),
                    parse_period(st.session_state.get('panel_period', '')),
                    st.session_state.get('panel_incomplete', False))
                context = build_context(snapshot.coverage, filters)
                st.session_state['panel_valid_ids'] = tuple(d.document_id for d in context.documents)
                timeline = context_timeline(snapshot, context, filters, config.withheld_document_ids)
                restrictions = component_restrictions(timeline.table)
                _summary(context, filters)
                render_annual(config.database, context, filters, snapshot.documents, restrictions, timeline.points)
                render_income(config.database, [d.document for d in context.documents], restrictions,
                              timeline.points, key='document_income')
                render_components(config.database, [d.document for d in context.documents], restrictions,
                                  key='document_components')
            except (ConfigurationError, InspectionError, ValueError):
                st.error('No se pudieron consultar los informes. Revisa los filtros de Análisis y la base configurada.')
