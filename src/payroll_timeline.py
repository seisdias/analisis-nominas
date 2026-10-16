"""Read-only timeline presentation; individual certified observations, never totals."""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import altair as alt
import streamlit as st

from src.canonical_inspection import InspectionError, open_inspector
from src.cli_config import ConfigurationError, load_config
from src.document_explorer import PRESENTATION_CURRENCY, STATUS_LABELS, format_amount

START_YEAR = 2006
SERIES = ('Bruto', 'Neto')


@dataclass(frozen=True)
class Timeline:
    points: list[dict[str, Any]]
    table: list[dict[str, Any]]
    ambiguous_periods: int


def prepare_timeline(records: list[dict[str, Any]], *, years: tuple[int, int],
                     company: str | None = None, series: tuple[str, ...] = SERIES) -> Timeline:
    """Conservative plotting guard, not a new documentary resolution policy.

    Keep unknown dates in the table. A company/month with competing documents or
    observations has no unique plotted value. Break lines between nonconsecutive
    actual months, without manufacturing missing records or zero amounts.
    """
    filtered = [r for r in records if (company is None or r['company_text'] == company)
                and (r['year'] is None or years[0] <= r['year'] <= years[1])]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in filtered:
        if all(row[k] is not None for k in ('company_text', 'year', 'month')):
            groups[(row['company_text'], row['year'], row['month'])].append(row)
    ambiguous = {key for key, rows in groups.items()
                 if len({r['document_id'] for r in rows}) > 1
                 or any(r['document_status'] == 'ambiguous'
                        or (len(r['version_ids']) > 1 and r['document_status'] == 'no_observation')
                        for r in rows)}
    points: list[dict[str, Any]] = []
    table = []
    previous: dict[tuple[str, str], tuple[int, int]] = {}
    for row in sorted(filtered, key=lambda r: (r['year'] is None or r['month'] is None,
            r['year'] or 0, r['month'] or 0, r['company_text'] or '', r['document_id'],
            r['series'], r['observation_id'] or '')):
        if row['series'] not in series:
            continue
        key = (row['company_text'], row['year'], row['month'])
        value = row['value']
        currency = value.get('currency')
        reason = ('Periodo ambiguo: documentos o candidatos múltiples' if key in ambiguous else
                  'Empresa o periodo incompleto' if any(v is None for v in key) else
                  'Divisa incompatible con EUR' if currency is not None and currency.code != PRESENTATION_CURRENCY else
                  'Sin importe certificado' if value['status'] != 'certified' or value.get('amount') is None else
                  'Representado')
        period = f'{row["year"] or "?"} / {row["month"]:02d}' if row['month'] else f'{row["year"] or "?"} / ?'
        table.append({'Periodo': period, 'Empresa': row['company_text'] or 'Empresa ausente o ambigua',
                      'Serie': row['series'], 'Importe': format_amount(value),
                      'Certificación': STATUS_LABELS[value['status']], 'Representación': reason,
                      'Documento': row['document_id'], 'Observación': row['observation_id'] or 'Sin observación',
                      'Versiones del documento': '\n'.join(row['version_ids']),
                      'Versiones del soporte': '\n'.join(row['source_version_ids']),
                      'Elegibilidad': row['eligibility'] or 'Sin observación'})
        if reason != 'Representado':
            continue
        index = row['year'] * 12 + row['month']
        group = (row['company_text'], row['series'])
        last, segment = previous.get(group, (index - 1, 0))
        segment += index != last + 1
        previous[group] = (index, segment)
        points.append({'Fecha': f'{row["year"]:04d}-{row["month"]:02d}-01',
                       'Empresa': row['company_text'], 'Serie': row['series'],
                       'Importe': float(value['amount'].to_decimal()), 'Importe exacto': format_amount(value),
                       'Documento': row['document_id'], 'Observación': row['observation_id'],
                       'Tramo': f'{segment}'})
    return Timeline(points, table, len(ambiguous))


def moving_average(points: list[dict[str, Any]], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trailing twelve actual months, per company/series, using exact source amounts.

    B.2 guards supply unique certified points. Incomplete context conservatively
    blocks any window it could belong to, even when no month can be plotted.
    The result is presentation-only and carries no documentary certification.
    """
    amounts = {r['observation_id']: r['value'].get('amount') for r in records}
    incomplete = [r for r in records if any(r[k] is None for k in ('company_text', 'year', 'month'))]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        groups[(point['Empresa'], point['Serie'])].append(point)
    result = []
    for (company, series), group in sorted(groups.items()):
        group.sort(key=lambda p: p['Fecha'])
        previous, segment = -1, 0
        for end in range(11, len(group)):
            window = group[end - 11:end + 1]
            dates = [(int(p['Fecha'][:4]), int(p['Fecha'][5:7])) for p in window]
            indices = [year * 12 + month for year, month in dates]
            if any(b != a + 1 for a, b in zip(indices, indices[1:])):
                continue
            if any((r['company_text'] is None or r['company_text'] == company)
                   and any((r['year'] is None or r['year'] == year)
                           and (r['month'] is None or r['month'] == month) for year, month in dates)
                   for r in incomplete):
                continue
            mean = sum((amounts[p['Observación']].to_decimal() for p in window), Decimal(0)) / 12
            segment += indices[-1] != previous + 1
            previous = indices[-1]
            display = f'{mean:,.2f}'.translate(str.maketrans(',.', '.,')) + ' € (media orientativa)'
            result.append({'Fecha': window[-1]['Fecha'], 'Empresa': company,
                           'Serie': f'{series} · Media móvil de 12 meses', 'Importe': float(mean),
                           'Importe exacto': display, 'Documento': '', 'Observación': '',
                           'Tramo': str(segment), 'Referencia': True})
    return result


def timeline_chart(points: list[dict[str, Any]], start: str, end: str,
                   averages: list[dict[str, Any]] | None = None) -> alt.Chart:
    """Separate companies, series and contiguous runs; no aggregate transforms."""
    chart = alt.Chart(alt.Data(values=points + averages if averages else points)).mark_line(point=True).encode(
        x=alt.X('Fecha:T', title='Periodo documental (mes)',
                scale=alt.Scale(domain=[start, end]), axis=alt.Axis(format='%m/%Y')),
        y=alt.Y('Importe:Q', title='Importe documental (€)', scale=alt.Scale(zero=False)),
        color=alt.Color('Empresa:N', title='Empresa'),
        strokeDash=alt.StrokeDash('Serie:N', title='Serie'),
        detail=alt.Detail('Tramo:N'),
        tooltip=[alt.Tooltip('Fecha:T', format='%m/%Y'), 'Empresa:N', 'Serie:N', 'Importe exacto:N', 'Documento:N', 'Observación:N'],
    ).properties(height=400).interactive()
    if averages:
        chart = chart.encode(strokeWidth=alt.condition('datum.Referencia === true', alt.value(3), alt.value(1)))
    return chart


def render_timeline() -> None:
    st.title('Evolución histórica de nóminas')
    st.caption('Evolución documental, no agregación certificada')
    try:
        config = load_config()
        with open_inspector(config.database) as inspector:
            records = inspector.timeline_records()
    except ConfigurationError as error:
        st.warning(str(error))
        return
    except InspectionError:
        st.error('Base no disponible o consulta fallida. Comprueba la configuración y la SQLite canónica v8. '
                 'La consulta es de solo lectura; no crea ni migra bases.')
        return
    if not records:
        st.info('No hay documentos en la base configurada.')
        return
    latest = max(((r['year'], r['month']) for r in records
                  if r['year'] is not None and r['month'] is not None), default=(START_YEAR, 1))
    last_year = max(START_YEAR, latest[0])
    with st.container(border=True):
        company = st.selectbox('Empresa documental', [None, *sorted({r['company_text'] for r in records
                                                                    if r['company_text'] is not None})],
                               format_func=lambda name: name or 'Todas las empresas', key='timeline_company')
        years = st.slider('Intervalo de años', START_YEAR, last_year, (START_YEAR, last_year)) if last_year > START_YEAR else (START_YEAR, START_YEAR)
        selected = st.multiselect('Series', SERIES, default=list(SERIES))
        show_average = st.checkbox('Mostrar media móvil de 12 meses')
    result = prepare_timeline(records, years=years, company=company, series=tuple(selected))
    st.caption('Series originales: valores documentales certificados, sin sumas ni promedios. '
               'Los meses sin puntos no equivalen a cero; las líneas se interrumpen en los huecos. '
               'La tabla conserva los importes exactos; el eje gráfico usa aproximación numérica.')
    if result.ambiguous_periods:
        st.warning(f'{result.ambiguous_periods} periodos de empresa ambiguos: consulta sus registros individuales en la tabla.')
    if any('Inconsistencia de divisa' in r['Importe'] for r in result.table):
        st.warning('Hay divisas incompatibles con EUR. Sus valores no se convierten ni se dibujan como euros.')
    if any('incompleto' in r['Representación'] for r in result.table):
        st.info('Los documentos con empresa o periodo incompleto permanecen en la tabla, aunque no puedan ubicarse en la gráfica.')
    averages = moving_average(result.points, records) if show_average else []
    if show_average:
        st.caption('Media estadística orientativa basada en observaciones documentales. '
                   'No constituye salario certificado. No equivale a una retribución mensual prorrateada.')
        st.info(f'{len(averages)} puntos de media móvil disponibles. Se requieren 12 meses consecutivos válidos '
                'de la misma empresa y serie dentro del intervalo seleccionado. Se omiten ventanas con huecos, '
                'ambigüedades, importes no certificados o divisas incompatibles. Los registros con contexto '
                'incompleto bloquean las ventanas a las que podrían pertenecer.')
    if result.points:
        end = f'{years[1]:04d}-{latest[1] if years[1] == latest[0] else 12:02d}-01'
        st.altair_chart(timeline_chart(result.points, f'{years[0]:04d}-01-01', end, averages), width='stretch')
        st.caption(f'{len(result.points)} puntos documentales · {len(result.table)} registros de series en la tabla.')
    else:
        st.info('No hay puntos representables para los filtros seleccionados.')
    st.subheader('Registros documentales')
    st.dataframe(result.table, hide_index=True, width='stretch', column_config={
        'Importe': st.column_config.TextColumn(alignment='right'),
        'Documento': st.column_config.TextColumn(width='large'),
    })
    with st.expander('Trazabilidad y ambigüedades'):
        st.write('Cada fila corresponde a una observación o a una serie sin observación de un documento. '
                 'Los identificadores de documento, observación y versiones permiten inspeccionar su soporte. '
                 'Se reutilizan los resultados de las decisiones documentales ya incorporadas a la base; '
                 'esta pantalla no elige versiones. Varias versiones sin observación o varios documentos '
                 'de una empresa en el mismo mes impiden representar una cifra mensual única. '
                 'La elegibilidad se conserva; evidence_only no autoriza agregaciones. '
                 'Los años desconocidos permanecen visibles al filtrar el intervalo.')
