"""Contextual Streamlit presentation over existing read-only contracts."""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from src.analysis_context import AnalysisContext, ContextFilters, build_context, parse_period
from src.analytic_dataset import DocumentCategory, read_analytic_dataset
from src.canonical.values import CanonicalValue, ValueState
from src.canonical_inspection import InspectionError, open_inspector
from src.cli_config import ConfigurationError, load_config
from src.component_view import TOTALS_DESCRIPTION, component_restrictions, render_components
from src.concepts_view import render_concepts
from src.coverage_view import CATEGORIES, REASONS, _details
from src.document_explorer import format_amount
from src.documentary_coverage import Availability, CoverageDocument
from src.gui_presentation import (
    canonical_value_text,
    format_period,
    friendly_timeline_rows,
    short_id,
)
from src.payroll_timeline import (
    CATEGORY_LABELS,
    Timeline,
    category_average,
    category_chart,
    category_visibility,
    classified_timeline,
    reset_categories,
    visible_timeline,
)


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


def _reset() -> None:
    reset_categories('panel_categories')
    for key in ('panel_company', 'panel_period', 'panel_incomplete', 'panel_document', 'panel_average'):
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


def render_panel() -> None:
    st.title('Panel de análisis')
    st.caption('Selecciona qué documentación quieres consultar. El detalle se adapta a tus filtros.')
    try:
        config = load_config()
        snapshot = load_panel(config.database, config.withheld_document_ids)
    except (ConfigurationError, InspectionError):
        st.error('No se pudo abrir la base configurada en solo lectura. Revisa la configuración y el acceso.')
        return
    with st.container(border=True):
        st.button('Restablecer filtros', key='panel_reset', on_click=_reset)
        left, right = st.columns(2)
        company = left.selectbox('Empresa', [None, *sorted({d.company for d in snapshot.coverage if d.company is not None})],
            format_func=lambda x: x if x is not None else 'Todas las empresas', key='panel_company', persist_state='session')
        text = right.text_input('Periodo', placeholder='Todo el histórico · Ej.: 2015 o 03/2015 – 09/2015',
            help='Vacío: histórico completo. Año: 2015. Mes: 09/2022. Intervalo inclusivo: 01/2015 – 06/2016.',
            key='panel_period', persist_state='session')
        incomplete = st.checkbox('Solo documentos con empresa o periodo incompleto', key='panel_incomplete', persist_state='session')
        try:
            period = parse_period(text)
        except ValueError as error:
            st.warning(str(error))
            return
        filters = ContextFilters(company, period, incomplete, st.session_state.get('panel_document'))
        context = build_context(snapshot.coverage, filters)
        if context.stale_selection:
            _clear_document()
            st.info('Se ha retirado la selección documental porque ya no coincide con empresa y periodo.')
        by_id = {d.document_id: d for d in context.candidates}
        st.session_state['panel_valid_ids'] = tuple(by_id)  # IDs only, never cached documents.
        selected = st.selectbox('Documento', [None, *by_id], format_func=lambda i: 'Todos los documentos compatibles' if i is None else
            f'{by_id[i].company or "Empresa desconocida"} · {format_period(by_id[i].year, by_id[i].month)} · '
            f'{CATEGORIES[by_id[i].document.category]} · {short_id(i)}', key='panel_document', persist_state='session')
    filters = ContextFilters(company, period, incomplete, selected)
    context = build_context(snapshot.coverage, filters)
    period_label = 'Histórico completo' if period is None else format_period(*period[0]) + ' – ' + format_period(*period[1])
    st.write('**Contexto:** ' + (company or 'Todas las empresas') + ' · ' + period_label
             + (' · Información incompleta' if incomplete else '') + (' · Documento ' + short_id(selected) if selected else ''))
    if period is not None:
        st.caption('Los documentos sin periodo completo no coinciden con un intervalo fechado. '
                   'Borra Periodo para localizarlos con el filtro de información incompleta.')
    if not context.documents:
        st.info('No hay coincidencias con los filtros activos. Retira un filtro o usa «Restablecer filtros».')
        if context.missing_months:
            st.caption(f'{len(context.missing_months)} meses sin documentación localizada en esta selección. '
                       + ('Hay contexto incompleto: ausencia incierta.' if context.gaps_uncertain else 'No equivale a salario cero.'))
        return
    timeline = context_timeline(snapshot, context, filters, config.withheld_document_ids)
    reasons = sorted({r['Representación'] for r in timeline.table if r['Representación'] != 'Representado'})
    if reasons:
        st.warning('Representación limitada: ' + '; '.join(reasons))
    if context.level == 'document':
        st.button('Volver al contexto', key='panel_back', on_click=_clear_document)
        try:
            _detail(config.database, context.documents[0], snapshot)
            render_components(config.database, [d.document for d in context.documents],
                              component_restrictions(timeline.table), key="panel_components")
        except InspectionError:
            st.error('No se pudo recuperar el soporte documental; no se ha cambiado la selección.')
        return
    _summary(context, filters)
    categories = category_visibility({CATEGORY_LABELS[d.document.category] for d in context.documents},
        key='panel_categories', label='Tipos de ingreso visibles')
    st.caption('La visibilidad solo cambia las series y la tabla económica; la cobertura y el inventario '
               'conservan todos los documentos del contexto. No resuelve ambigüedades ni restricciones.')
    visible = visible_timeline(timeline, categories)
    if context.level != 'month' and len(context.months) > 1:
        st.subheader('Evolución documental individual')
        st.caption(TOTALS_DESCRIPTION)
        show_average = st.checkbox('Mostrar media móvil de 12 meses', key='panel_average', persist_state='session')
        averages = category_average(timeline.points, snapshot.timeline,
            classified=True) if show_average else []
        if CATEGORY_LABELS[DocumentCategory.ORDINARY] not in categories:
            averages = []
        if show_average:
            st.caption('Referencia de totales documentales completos: no descuenta bonus, extras ni prorratas; no es salario recurrente.')
            st.caption(f'{len(averages)} puntos de media orientativa; no es salario certificado ni prorrateado. '
                       'Exige 12 meses consecutivos válidos, sin multipago, huecos ni mezcla de categorías.')
        if visible.points:
            start, end = period or (context.months[0], context.months[-1])
            st.altair_chart(category_chart(visible.points, f'{start[0]:04d}-{start[1]:02d}-01',
                                          f'{end[0]:04d}-{end[1]:02d}-01', averages), width='stretch')
        else:
            st.info('Sin puntos representables; los documentos siguen disponibles en la tabla.')
    render_components(config.database, [d.document for d in context.documents],
                      component_restrictions(timeline.table), key='panel_components')
    st.subheader('Registros económicos visibles')
    st.dataframe(friendly_timeline_rows(visible.table), hide_index=True, column_config={
        'Importe': st.column_config.TextColumn(alignment='right')})
    st.subheader('Documentos disponibles')
    st.caption('Para ampliar una nómina, selecciónala en Documento. No se elige ni fusiona ninguna automáticamente.')
    st.dataframe(_document_rows(snapshot, context), hide_index=True, width='stretch', column_config={
        'Bruto': st.column_config.TextColumn(alignment='right'), 'Neto': st.column_config.TextColumn(alignment='right')})
    st.caption('Importes documentales individuales. Certificación no implica agregabilidad; evidence_only se conserva. '
               'La denominación documental no se equipara a identidad empresarial canónica.')
