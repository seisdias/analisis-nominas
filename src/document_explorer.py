"""Presentation of canonical inspection results; no economic policy or storage writes."""

from hashlib import sha256
from typing import Any

import streamlit as st

from src.canonical_inspection import InspectionError, open_inspector
from src.cli_config import ConfigurationError, load_config
from src.gui_presentation import format_period, short_id

# Application scope only; never persisted as documentary currency.
PRESENTATION_CURRENCY = 'EUR'
PRESENTATION_SYMBOL = '€'

STATUS_LABELS = {
    'certified': 'Certificado',
    'no_observation': 'Sin observación',
    'not_certified': 'No certificado',
    'ambiguous': 'Ambiguo',
}
MONTHS = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
          'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')


def format_amount(value: dict[str, Any]) -> str:
    """Display certified values in application currency without changing evidence."""
    if value['status'] != 'certified':
        return STATUS_LABELS.get(value['status'], 'No disponible')
    amount = value.get('amount')
    if amount is None:
        return 'Importe ausente'
    currency = value.get('currency')
    if currency is not None and currency.code != PRESENTATION_CURRENCY:
        return f'Inconsistencia de divisa: {currency.code} (ámbito {PRESENTATION_CURRENCY})'
    # At least two decimals, retaining all additional certified decimal places.
    number = format(amount.to_decimal(), f',.{max(2, amount.scale)}f')
    number = number.translate(str.maketrans(',.', '.,'))
    return f'{number} {PRESENTATION_SYMBOL}'


def document_row(row: dict[str, Any]) -> dict[str, str]:
    """Keep documentary context separate from the two value certifications."""
    return {
        'Identificador': short_id(row['document_id']),
        'Empresa documental': row['company_text'] or 'Empresa ausente o ambigua',
        'Periodo documental': format_period(row['year'], row['month']),
        'Bruto': format_amount(row['gross']),
        'Neto': format_amount(row['net']),
        'Certificación de valores': 'Bruto: ' + STATUS_LABELS[row['gross']['status']]
                                   + ' · Neto: ' + STATUS_LABELS[row['net']['status']],
    }


def ordered_documents(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort complete documentary periods first; never infer missing components."""
    return sorted(rows, key=lambda row: (
        row['year'] is None or row['month'] is None,
        -(row['year'] or 0), -(row['month'] or 0), row['document_id']))


def document_counts(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Count logical identities, requiring unambiguous certified gross AND net."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row['document_id'], []).append(row)
    certified = 0
    for group in groups.values():
        if all(row[field]['status'] == 'certified' and row[field].get('amount') is not None
               and row[field] == group[0][field]
               for row in group for field in ('gross', 'net')):
            certified += 1
    return len(groups), certified


def render_app() -> None:
    st.title('Análisis de Nóminas')
    st.caption('Explorador documental')
    st.badge(f'Ámbito {PRESENTATION_CURRENCY}', color='blue')
    with st.expander('Configuración y diagnóstico'):
        try:
            config = load_config()
        except ConfigurationError as error:
            st.warning(f'Base de datos no configurada o configuración inválida. {error}')
            return
        # Explicit diagnostic section only; never log paths or raw exceptions.
        st.text(f'Base SQLite efectiva: {config.database}')
        st.text(f'Procedencia de la base: {config.source}')
        st.text(f'Directorio documental: {config.payroll_directory or "No configurado"}')
        st.caption('El directorio documental es informativo; no se leen ni modifican PDF. '
                   'Las rutas relativas se resuelven desde la raíz del repositorio.')
        access_status = st.empty()

    try:
        # One fresh read-only snapshot per rerun; no cache of private payroll data.
        with open_inspector(config.database) as inspector:
            access_status.success('SQLite accesible en solo lectura. Esquema v8, integridad y '
                                  'claves foráneas verificados.')
            companies = inspector.companies()
            with st.container(border=True):
                company_filter, year_filter, month_filter = st.columns([3, 1, 1])
                company = company_filter.selectbox(
                    'Empresa documental',
                    [None, *(item['company_text'] for item in companies['companies'])],
                    format_func=lambda name: 'Todas las empresas' if name is None else name,
                    help='Denominación documental exacta, sin inferir identidad empresarial.',
                )
                year_text = year_filter.text_input(
                    'Año', placeholder='Todos', max_chars=4,
                    help='Año entre 1 y 9999. Vacío incluye todos los años.')
                month = month_filter.selectbox(
                    'Mes', [None, *range(1, 13)],
                    format_func=lambda value: 'Todos' if value is None else MONTHS[value - 1])
            year = None
            if year_text.strip():
                if not year_text.strip().isascii() or not year_text.strip().isdigit():
                    st.warning('Introduce un año entero entre 1 y 9999 o deja el campo vacío.')
                    return
                year = int(year_text.strip())
                if not 1 <= year <= 9999:
                    st.warning('Introduce un año entero entre 1 y 9999 o deja el campo vacío.')
                    return
            rows = ordered_documents(inspector.documents(company=company, year=year, month=month))
    except InspectionError:
        access_status.error('No se pudo consultar la base de datos: comprueba la ruta, permisos, '
                            'esquema v8 y journal DELETE. No se crea ni migra ninguna base.')
        st.error('No se pudo consultar la base de datos. Comprueba el acceso, que sea canónica '
                 'v8 y que use journal DELETE. No se ha creado ni migrado ninguna base.')
        return

    total, certified = document_counts(rows)
    with st.container(horizontal=True):
        st.metric('Documentos encontrados', total, border=True,
                  help='Documentos lógicos únicos que cumplen los filtros.')
        st.metric('Bruto y neto certificados', certified, border=True,
                  help='Documentos con ambos valores inequívocamente certificados. '
                       'No implica que se puedan sumar ni certifica su divisa.')

    currencies = sorted({value['currency'].code for row in rows
                         for value in (row['gross'], row['net'])
                         if value.get('currency') is not None
                         and value['currency'].code != PRESENTATION_CURRENCY})
    if currencies:
        st.warning('Inconsistencia de divisa: ' + ', '.join(currencies)
                   + f'. El ámbito de la aplicación es {PRESENTATION_CURRENCY}; '
                   'estos importes no se convierten ni se presentan como euros.')

    st.subheader('Documentos')
    if not rows:
        st.info('No hay documentos para los filtros seleccionados.')
    else:
        st.caption('Más recientes primero · Selecciona una fila para consultar su identificación.')
        # Reset selection when filters/order change, so it never identifies another document.
        selection_key = sha256(repr((company, year, month,
                                    [row['document_id'] for row in rows])).encode()).hexdigest()
        event = st.dataframe(
            [document_row(row) for row in rows], hide_index=True, width='stretch',
            column_order=['Periodo documental', 'Empresa documental', 'Bruto', 'Neto'],
            column_config={
                'Periodo documental': st.column_config.TextColumn('Periodo', width='small'),
                'Empresa documental': st.column_config.TextColumn('Empresa', width='medium'),
                'Bruto': st.column_config.TextColumn(alignment='right', width='medium'),
                'Neto': st.column_config.TextColumn(alignment='right', width='medium'),
                'Identificador': st.column_config.TextColumn(width='large'),
            }, on_select='rerun', selection_mode='single-row', key='documents-' + selection_key)
        if event.selection.rows:
            selected = rows[event.selection.rows[0]]
            with st.container(border=True):
                st.caption('Identificador del documento')
                st.code(selected['document_id'], language=None, wrap_lines=True)
                st.text(document_row(selected)['Certificación de valores'])
                try:
                    with open_inspector(config.database) as inspector:
                        detail = inspector.document(selected['document_id'])
                    for version in detail['versions']:
                        st.caption('SHA-256 del archivo · ' + short_id(version['version'].version_id))
                        st.code(version['source_file'].sha256, language=None, wrap_lines=True)
                except InspectionError:
                    st.warning('No se pudo recuperar el soporte documental.')

    with st.expander('Cómo interpretar los documentos', icon=':material/info:'):
        st.write('El periodo es documental; no presupone liquidación ni devengo. '
                 'Los periodos incompletos aparecen al final. Documentos distintos del mismo '
                 'periodo se conservan por separado.')
        st.write('Certificado: valor respaldado por la certificación existente. '
                 'Sin observación: no hay un importe evaluado; no significa cero ni ausencia documental. '
                 'Ambiguo: varias observaciones, sin elegir una. '
                 'No certificado: el valor no supera la certificación existente.')
        st.write(f'Ámbito {PRESENTATION_CURRENCY}: los valores certificados sin moneda registrada '
                 'se presentan en euros, sin modificar la evidencia. Una divisa distinta genera '
                 'una advertencia. Certificar un valor no implica que se pueda sumar.')
        if companies['unassigned_documents']:
            st.caption('Hay documentos con empresa ausente o ambigua, accesibles en '
                       '«Todas las empresas». Los filtros requieren campos concordantes.')
