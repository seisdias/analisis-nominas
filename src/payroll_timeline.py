"""Read-only timeline presentation; individual certified observations, never totals."""
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
from typing import Any

import altair as alt
import streamlit as st

from src.analytic_dataset import AnalyticDocument, DocumentCategory, load_analytic_dataset
from src.canonical.values import ValueState
from src.canonical_inspection import InspectionError, open_inspector
from src.cli_config import ConfigurationError, load_config
from src.document_explorer import PRESENTATION_CURRENCY, STATUS_LABELS, format_amount
from src.gui_presentation import format_period, friendly_timeline_rows, short_id

START_YEAR = 2006
SERIES = ('Bruto', 'Neto')
CATEGORY_LABELS = {
    DocumentCategory.ORDINARY: 'Nóminas ordinarias',
    DocumentCategory.EXTRA: 'Pagas extraordinarias',
    DocumentCategory.BENEFITS: 'Pagas de beneficios',
    DocumentCategory.ARREARS_ADJUSTMENT: 'Otros ingresos económicos',
    DocumentCategory.SETTLEMENT: 'Otros ingresos económicos',
    DocumentCategory.OTHER: 'Otros ingresos económicos',
    DocumentCategory.UNCLASSIFIED: 'Documentos sin clasificar',
}
CATEGORIES = tuple(dict.fromkeys(CATEGORY_LABELS.values()))


@dataclass(frozen=True)
class Timeline:
    points: list[dict[str, Any]]
    table: list[dict[str, Any]]
    ambiguous_periods: int


def _documentary_text(doc: AnalyticDocument, name: str) -> str | None:
    """Require agreeing present facts from every extraction; never fill omissions."""
    extractions = {e for v in doc.provenance for e in v.extraction_ids}
    facts = [f for f in doc.context_facts if f.fact_key in ('nomina.' + name, 'payload/' + name)]
    if not extractions or {f.extraction_id for f in facts} != extractions:
        return None
    if any(f.value.state != ValueState.PRESENT or not isinstance(f.value.value, str) for f in facts):
        return None
    values = {f.value.value for f in facts}
    value = next(iter(values)) if len(values) == 1 else None
    return value if isinstance(value, str) else None


def _documentary_interval(doc: AnalyticDocument) -> tuple[date, date] | None:
    values = [_documentary_text(doc, name) for name in ('fecha_inicio', 'fecha_fin')]
    if any(v is None for v in values):
        return None
    try:
        start, end = (date.fromisoformat(v) for v in values if v is not None)
    except ValueError:
        return None
    if [start.isoformat(), end.isoformat()] != values:
        return None
    return (start, end) if start <= end else None


def _multipayment_supported(rows: list[dict[str, Any]], dataset: Sequence[AnalyticDocument]) -> bool:
    """Documentary distinction only: no replacement, independence or additivity decision.

    The existing classifier must be backed by explicit type facts and a unique
    version. Equal-category documents additionally need nonoverlapping explicit
    intervals. Missing or competing evidence keeps the presentation blocked.
    """
    documents = []
    for identity in sorted({r['document_id'] for r in rows}):
        matches = [d for d in dataset if d.document_id == identity]
        if len(matches) != 1:
            return False
        doc = matches[0]
        if (doc.classification_document_id != identity or len(doc.provenance) != 1
                or doc.category in (DocumentCategory.UNCLASSIFIED, DocumentCategory.OTHER)
                or _documentary_text(doc, 'tipo') != doc.original_document_type):
            return False
        version = doc.provenance[0].version_id
        if any(tuple(r['version_ids']) != (version,) or tuple(r['source_version_ids']) != (version,)
               for r in rows if r['document_id'] == identity):
            return False
        documents.append(doc)
    for left, right in combinations(documents, 2):
        if left.category != right.category:
            continue
        a, b = _documentary_interval(left), _documentary_interval(right)
        if a is None or b is None or not (a[1] < b[0] or b[1] < a[0]):
            return False
    return True


def prepare_timeline(records: list[dict[str, Any]], *, years: tuple[int, int],
                     company: str | None = None, series: tuple[str, ...] = SERIES,
                     dataset: Sequence[AnalyticDocument] = (),
                     withheld_document_ids: frozenset[str] = frozenset()) -> Timeline:
    """Conservative plotting guard, not a new documentary resolution policy.

    Keep unknown dates in the table. A company/month with competing documents or
    observations remains blocked unless documentary differentiation is evidenced.
    Break lines between nonconsecutive months and around multipayment points,
    without manufacturing missing records or zero amounts.
    """
    filtered = [r for r in records if (company is None or r['company_text'] == company)
                and (r['year'] is None or years[0] <= r['year'] <= years[1])]
    filtered = [row for i, row in enumerate(filtered) if row not in filtered[:i]]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in filtered:
        if all(row[k] is not None for k in ('company_text', 'year', 'month')):
            groups[(row['company_text'], row['year'], row['month'])].append(row)
    multipayment = {key for key, rows in groups.items() if len({r['document_id'] for r in rows}) > 1}
    withheld_periods = {key for key, rows in groups.items()
                        if any(r["document_id"] in withheld_document_ids for r in rows)}
    ambiguous = set(withheld_periods)
    for key, rows in groups.items():
        competing = any(len([r for r in rows if (r['document_id'], r['series']) == pair]) > 1
                        for pair in {(r['document_id'], r['series']) for r in rows})
        if (competing or any(r['document_status'] == 'ambiguous'
                or (len(r['version_ids']) > 1 and r['document_status'] == 'no_observation') for r in rows)
                or (key in multipayment and not _multipayment_supported(rows, dataset))):
            ambiguous.add(key)
    intervals = {d.document_id: _documentary_interval(d) for d in dataset}
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
        reason = ('Revisión pendiente: restricción de presentación'
                  if key in withheld_periods or row['document_id'] in withheld_document_ids else
                  'Periodo ambiguo: documentos o candidatos múltiples' if key in ambiguous else
                  'Empresa o periodo incompleto' if any(v is None for v in key) else
                  'Divisa incompatible con EUR' if currency is not None and currency.code != PRESENTATION_CURRENCY else
                  'Sin importe certificado' if value['status'] != 'certified' or value.get('amount') is None else
                  'Representado')
        interval = intervals.get(row['document_id'])
        interval_text = f'{interval[0].isoformat()} → {interval[1].isoformat()}' if interval else 'No disponible'
        period = format_period(row['year'], row['month'])
        table.append({'Periodo': period, 'Empresa': row['company_text'] or 'Empresa ausente o ambigua',
                      'Serie': row['series'], 'Importe': format_amount(value),
                      'Intervalo documental': interval_text,
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
        segment += index != last + 1 or key in multipayment
        previous[group] = (index, segment + int(key in multipayment))
        points.append({'Fecha': f'{row["year"]:04d}-{row["month"]:02d}-01',
                       'Empresa': row['company_text'], 'Serie': row['series'],
                       'Importe': float(value['amount'].to_decimal()), 'Importe exacto': format_amount(value),
                       'Documento': row['document_id'], 'Observación': row['observation_id'],
                       'Tramo': f'{segment}', 'Multipago': key in multipayment,
                       'Intervalo documental': interval_text})
    return Timeline(points, table, len(ambiguous))


def document_categories(dataset: Sequence[AnalyticDocument]) -> dict[str, str]:
    """Join only by unique full logical identity, never by company/date/amount."""
    grouped: dict[str, list[AnalyticDocument]] = defaultdict(list)
    for doc in dataset:
        grouped[doc.document_id].append(doc)
    return {identity: CATEGORY_LABELS[docs[0].category]
            for identity, docs in grouped.items()
            if len(docs) == 1 and docs[0].classification_document_id == identity}


def classified_timeline(records: list[dict[str, Any]], dataset: Sequence[AnalyticDocument], *,
                        years: tuple[int, int], company: str | None = None,
                        series: tuple[str, ...] = SERIES,
                        categories: tuple[str, ...] = CATEGORIES,
                        withheld_document_ids: frozenset[str] = frozenset()) -> Timeline:
    # Evaluate the full context BEFORE filtering; hiding evidence cannot resolve it.
    original = prepare_timeline(records, years=years, company=company, series=series, dataset=dataset,
                                withheld_document_ids=withheld_document_ids)
    labels = document_categories(dataset)
    def selected(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched = [dict(row, Categoría=labels.get(row['Documento'], CATEGORIES[-1])) for row in rows]
        return [row for row in enriched if row['Categoría'] in categories]
    points = selected(original.points)
    previous: dict[tuple[str, str, str], tuple[int, int]] = {}
    for point in points:
        index = int(point['Fecha'][:4]) * 12 + int(point['Fecha'][5:7])
        key = (point['Empresa'], point['Serie'], point['Categoría'])
        last, segment = previous.get(key, (index - 1, 0))
        segment += index != last + 1 or point['Multipago']
        previous[key] = (index, segment + int(point['Multipago']))
        point['Tramo'] = str(segment)
    return Timeline(points, selected(original.table), original.ambiguous_periods)


def category_average(points: list[dict[str, Any]], records: list[dict[str, Any]], *,
                     classified: bool) -> list[dict[str, Any]]:
    eligible = [p for p in points if p['Categoría'] == CATEGORIES[0]] if classified else points
    return moving_average(eligible, records)


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
        if not point.get('Multipago', False):
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


def category_chart(points: list[dict[str, Any]], start: str, end: str,
                   averages: list[dict[str, Any]]) -> alt.LayerChart | alt.FacetChart:
    """Ordinary lines and isolated category markers, without economic transforms."""
    displayed = [dict(p, Documento=short_id(p['Documento']), Observación=short_id(p['Observación']))
                 for p in points]
    lines = [p for p in displayed if p['Categoría'] == CATEGORIES[0] and not p.get('Multipago', False)]
    markers = [p for p in displayed if p['Categoría'] != CATEGORIES[0] or p.get('Multipago', False)]
    base = alt.Chart().encode(
        x=alt.X('Fecha:T', title='Periodo documental (mes)', scale=alt.Scale(domain=[start, end]),
                axis=alt.Axis(format='%m/%Y')),
        y=alt.Y('Importe:Q', title='Importe (€)', scale=alt.Scale(zero=False)),
        color=alt.Color('Empresa:N', title='Empresa'),
        tooltip=[alt.Tooltip('Fecha:T', format='%m/%Y'), 'Empresa:N', 'Categoría:N', 'Serie:N',
                 alt.Tooltip('Importe exacto:N', title='Importe'), 'Documento:N', 'Observación:N', 'Intervalo documental:N'])
    ordinary = base.properties(data=alt.Data(values=lines)).mark_line(point=True).encode(
        strokeDash='Serie:N', detail='Tramo:N')
    isolated = base.properties(data=alt.Data(values=markers)).mark_point(size=100, filled=True).encode(
        shape=alt.Shape('Categoría:N', title='Tipo de ingreso',
                        scale=alt.Scale(domain=list(CATEGORIES), range=['circle', 'diamond', 'triangle-up', 'square', 'cross'])),
        opacity=alt.Opacity('Serie:N', scale=alt.Scale(domain=list(SERIES), range=[1, 0.45])))
    reference = base.properties(data=alt.Data(values=averages)).mark_line(strokeWidth=3, point=True).encode(
        strokeDash='Serie:N', detail='Tramo:N')
    return alt.layer(ordinary, isolated, reference).properties(height=400).interactive()


def reset_timeline_filters() -> None:
    for key in ('timeline_company', 'timeline_years', 'timeline_series', 'timeline_categories', 'timeline_average'):
        st.session_state.pop(key, None)


def render_timeline_details(rows: list[dict[str, Any]], dataset: Sequence[AnalyticDocument]) -> None:
    if not rows:
        return
    with st.expander('Identificadores completos y soporte documental'):
        key = sha256(repr(rows).encode()).hexdigest()
        index = st.selectbox('Consultar un registro', [None, *range(len(rows))],
            format_func=lambda i: 'Selecciona un registro' if i is None else
                f"{i + 1}. {rows[i]['Periodo']} · {rows[i]['Empresa']} · {rows[i]['Serie']} · {short_id(rows[i]['Documento'])}",
            key='timeline-detail-' + key)
        if index is not None:
            row = rows[index]
            for field in ('Documento', 'Observación', 'Versiones del documento', 'Versiones del soporte'):
                st.caption(field)
                st.code(row[field], language=None, wrap_lines=True)
            st.caption('Elegibilidad: ' + row['Elegibilidad'])
            for doc in dataset:
                if doc.document_id == row['Documento']:
                    for version in doc.provenance:
                        st.caption('SHA-256 del archivo · ' + short_id(version.version_id))
                        st.code(version.file_sha256, language=None, wrap_lines=True)


def render_timeline() -> None:
    st.title('Evolución histórica de nóminas')
    st.caption('Evolución documental, no agregación certificada')
    try:
        config = load_config()
        with open_inspector(config.database) as inspector:
            records = inspector.timeline_records()
        dataset = load_analytic_dataset(config.database)
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
    labels = document_categories(dataset)
    available = {labels.get(r['document_id'], CATEGORIES[-1]) for r in records}
    classified = any(label != CATEGORIES[-1] for label in available)
    with st.container(border=True):
        st.button('Restablecer filtros', on_click=reset_timeline_filters)
        company = st.selectbox('Empresa documental', [None, *sorted({r['company_text'] for r in records
                                                                    if r['company_text'] is not None})],
                               format_func=lambda name: name or 'Todas las empresas', key='timeline_company')
        years = st.slider('Intervalo de años', START_YEAR, last_year, (START_YEAR, last_year), key='timeline_years') if last_year > START_YEAR else (START_YEAR, START_YEAR)
        selected = st.multiselect('Series', SERIES, default=list(SERIES), key='timeline_series')
        show_average = st.checkbox('Mostrar media móvil de 12 meses', key='timeline_average')
        categories = st.multiselect('Tipos de ingreso', CATEGORIES, default=[c for c in CATEGORIES if c in available],
            format_func=lambda c: c if c in available else c + ' · Sin registros', key='timeline_categories')
    result = classified_timeline(records, dataset, years=years, company=company, series=tuple(selected),
                                 categories=tuple(categories),
                                 withheld_document_ids=frozenset(config.withheld_document_ids))
    st.caption('Series originales: valores documentales certificados, sin sumas ni promedios. '
               'Los meses sin puntos no equivalen a cero; las líneas se interrumpen en los huecos. '
               'La tabla conserva los importes exactos; el eje gráfico usa aproximación numérica.')
    if config.withheld_document_ids:
        st.info('Hay restricciones locales de presentación por revisión pendiente. '
                'No modifican la clasificación ni la evidencia; los periodos afectados permanecen en la tabla.')
    if result.ambiguous_periods:
        st.warning(f'{result.ambiguous_periods} periodos de empresa ambiguos o pendientes: consulta sus registros individuales en la tabla.')
    if any('Inconsistencia de divisa' in r['Importe'] for r in result.table):
        st.warning('Hay divisas incompatibles con EUR. Sus valores no se convierten ni se dibujan como euros.')
    if any('incompleto' in r['Representación'] for r in result.table):
        st.info('Los documentos con empresa o periodo incompleto permanecen en la tabla, aunque no puedan ubicarse en la gráfica.')
    averages = category_average(result.points, records, classified=classified) if show_average else []
    if show_average:
        st.caption('Media sobre nóminas ordinarias identificadas por C.1.' if classified else
                   'Referencia documental B.3: no hay clasificación utilizable; no identifica un salario ordinario.')
        st.caption('Media estadística orientativa basada en observaciones documentales. '
                   'No constituye salario certificado. No equivale a una retribución mensual prorrateada.')
        st.info(f'{len(averages)} puntos de media móvil disponibles. Se requieren 12 meses consecutivos válidos '
                'de la misma empresa y serie dentro del intervalo seleccionado. Se omiten ventanas con huecos, '
                'ambigüedades, meses multipago, importes no certificados o divisas incompatibles. Los registros con contexto '
                'incompleto bloquean las ventanas a las que podrían pertenecer.')
    if result.points:
        end = f'{years[1]:04d}-{latest[1] if years[1] == latest[0] else 12:02d}-01'
        st.altair_chart(category_chart(result.points, f'{years[0]:04d}-01-01', end, averages), width='stretch')
        st.caption(f'{len(result.points)} puntos documentales · {len(result.table)} registros de series en la tabla.')
    else:
        st.info('No hay puntos representables para los filtros seleccionados.')
    st.subheader('Registros documentales')
    st.dataframe(friendly_timeline_rows(result.table), hide_index=True, width='stretch', column_config={
        'Importe': st.column_config.TextColumn(alignment='right'),
        'Documento': st.column_config.TextColumn(width='large'),
    })
    render_timeline_details(result.table, dataset)
    with st.expander('Trazabilidad y ambigüedades'):
        st.write('Las categorías proceden del dataset C.1 y se enlazan solo por identificador completo. '
                 'Sin correspondencia única se muestra «Documentos sin clasificar». Otros ingresos agrupa '
                 'las categorías de atrasos, finiquitos y otros documentos, sin sumar sus importes. '
                 'Los marcadores no implican que un documento sea un ingreso adicional acumulable.')
        st.write('Cada fila corresponde a una observación o a una serie sin observación de un documento. '
                 'Los identificadores de documento, observación y versiones permiten inspeccionar su soporte. '
                 'Se reutilizan los resultados de las decisiones documentales ya incorporadas a la base; '
                 'esta pantalla no elige versiones. Los documentos diferenciados por tipos explícitos o '
                 'intervalos documentados no solapados se muestran como puntos separados, sin línea ni media. '
                 'La multiplicidad sin soporte suficiente permanece bloqueada. Los intervalos se muestran '
                 'como evidencia documental, sin convertirlos en periodos de liquidación. '
                 'La elegibilidad se conserva; evidence_only no autoriza agregaciones. '
                 'Los años desconocidos permanecen visibles al filtrar el intervalo.')
