"""Streamlit documentary coverage: counts and traceability, no economic arithmetic."""
import streamlit as st

from src.analytic_dataset import DocumentCategory
from src.canonical_inspection import InspectionError
from src.cli_config import ConfigurationError, load_config
from src.documentary_coverage import (
    Availability,
    CoverageDocument,
    ReviewReason,
    load_coverage,
    summarize_coverage,
)
from src.gui_presentation import format_period, short_id

STATUS = {
    Availability.CERTIFIED: 'Certificado (inspector)',
    Availability.NO_OBSERVATION: 'Sin observación',
    Availability.NOT_CERTIFIED: 'Observación no certificada',
    Availability.AMBIGUOUS: 'Observaciones múltiples',
}
CATEGORIES = {
    DocumentCategory.ORDINARY: 'Nómina ordinaria',
    DocumentCategory.EXTRA: 'Paga extraordinaria',
    DocumentCategory.BENEFITS: 'Paga de beneficios',
    DocumentCategory.ARREARS_ADJUSTMENT: 'Atrasos / regularización',
    DocumentCategory.SETTLEMENT: 'Finiquito / liquidación',
    DocumentCategory.OTHER: 'Otro documento económico',
    DocumentCategory.UNCLASSIFIED: 'Sin clasificación suficiente',
}
REASONS = {
    ReviewReason.CONTEXT_INCOMPLETE: 'Empresa o periodo incompleto',
    ReviewReason.CATEGORY_UNCLASSIFIED: 'Clasificación insuficiente',
    ReviewReason.OBSERVATION_MISSING: 'Falta observación de bruto o neto',
    ReviewReason.OBSERVATION_AMBIGUOUS: 'Observaciones competidoras',
    ReviewReason.CERTIFICATION_BLOCKED: 'Certificación bloqueada',
}


def _details(record: CoverageDocument) -> None:
    doc = record.document
    st.caption('Documento lógico completo')
    st.code(doc.document_id, language=None, wrap_lines=True)
    st.text('Tipo documental original: ' + doc.original_document_type)
    st.text('Clasificación: ' + CATEGORIES[doc.category])
    st.caption('Elegibilidad conservada: ' + (', '.join(doc.eligibilities) or 'Sin observaciones'))
    st.caption('Contexto y clasificación: identificadores de hechos')
    st.code('\n'.join(f.fact_id for f in doc.context_facts) or 'Sin hechos de contexto', language=None)
    for version in doc.provenance:
        with st.expander('Versión ' + short_id(version.version_id)):
            st.code(version.version_id, language=None)
            st.caption('Archivo / SHA-256')
            st.code(version.file_id, language=None)
            st.code(version.file_sha256, language=None)
            st.text('Páginas del documento: ' + (', '.join(map(str, version.pages)) or 'No disponibles'))
            st.caption('Extracciones')
            st.code('\n'.join(version.extraction_ids) or 'Sin extracciones', language=None)
    with st.expander('Observaciones y hechos de soporte'):
        for observation, facts in doc.observation_facts:
            st.caption('Observación → hechos; no autoriza sumar')
            st.code(observation + '\n' + '\n'.join(facts), language=None)


def render_coverage() -> None:
    st.title('Cobertura documental')
    st.caption('Qué documentación existe y qué información está disponible; no son ingresos ni salarios acumulados.')
    try:
        config = load_config()
        records = load_coverage(config.database, withheld_document_ids=config.withheld_document_ids)
    except ConfigurationError as error:
        st.warning(str(error))
        return
    except InspectionError:
        st.error('No se pudo consultar la SQLite canónica v8. No se crea, modifica ni migra ninguna base.')
        return
    if not records:
        st.info('No hay documentos en la base configurada.')
        return
    known_years = sorted({d.year for d in records if d.year is not None})
    with st.container(border=True):
        company = st.selectbox('Empresa documental exacta',
            [None, *sorted({d.company for d in records if d.company is not None})],
            format_func=lambda value: value if value is not None else 'Todas las empresas', key='coverage_company')
        if known_years:
            low, high = known_years[0], known_years[-1]
            years = st.slider('Intervalo de años', low, high, (low, high), key='coverage_years') if low < high else (low, high)
        else:
            years = (1, 1)  # No dated rows; never display this internal placeholder.
            st.info('No hay años documentales conocidos. Se muestran los documentos sin asignar periodo.')
    report = summarize_coverage(records, years=years, company=company)
    with st.container(horizontal=True):
        st.metric('Documentos lógicos', len(report.document_ids))
        st.metric('Bruto y neto certificados · inspector', len(report.certified_both))
        st.metric('Bruto y neto disponibles · C.1', len(set(report.analytic_gross) & set(report.analytic_net)))
    st.caption('El inspector certifica observaciones con soporte único. C.1 exige además una sola versión '
               'documental: menor disponibilidad C.1 no significa pérdida de evidencia ni invalidez de resoluciones existentes. '
               'Certificado no significa candidato ni sumable; evidence_only permanece intacto.')
    if any(d.year is None for d in report.documents):
        st.info('Los documentos sin año conocido siguen incluidos, separados del intervalo fechado.')
    if company is not None and any(d.company is None for d in records):
        st.info('Hay documentos sin empresa asignable fuera de este filtro. Consulta «Todas las empresas» para revisarlos.')
    buckets = {'Todos los documentos': report.document_ids,
               'Bruto y neto certificados · inspector': report.certified_both,
               'Bruto disponible · C.1': report.analytic_gross,
               'Neto disponible · C.1': report.analytic_net,
               'Bruto y neto disponibles · C.1': tuple(i for i in report.analytic_gross if i in report.analytic_net),
               'Bruto no disponible · C.1': tuple(i for i in report.document_ids if i not in report.analytic_gross),
               'Neto no disponible · C.1': tuple(i for i in report.document_ids if i not in report.analytic_net),
               'Documentos multiversión': report.multiversion_ids,
               'Incidencias para revisión': report.review_ids,
               'Restricciones locales de presentación': report.restricted_ids}
    st.subheader('Empresas, años y meses documentados')
    st.caption('Un mes ausente significa ausencia de documentación en el corpus consultado; no significa desempleo '
               'ni salario cero. Los huecos con contexto incompleto son inciertos. Dos documentos del mismo mes '
               'cuentan como dos documentos y un solo mes. No se mide liquidación, devengo ni meses trabajados.')
    group_rows = []
    for group_index, group in enumerate(report.groups, 1):
        if not known_years and group.year is not None:
            continue
        name = group.company if group.company is not None else 'Empresa sin asignar'
        year = str(group.year) if group.year is not None else 'Año sin asignar'
        group_rows.append({'Empresa documental': name, 'Año': year,
            'Documentos': len(group.document_ids),
            'Meses documentados': ', '.join(f'{m:02d}' for m in group.months) or 'Ninguno asignado',
            'Meses ausentes / sin asignar': (', '.join(f'{m:02d}' for m in group.missing_months) or 'Ninguno') if group.year else 'NO DISPONIBLE',
            'Interpretación de los huecos': 'Ausencia documental en este corpus' if group.absence_certain else 'Incierta: contexto incompleto'})
        buckets[f'Empresa/año {group_index} · {name} · {year}'] = group.document_ids
    st.dataframe(group_rows, hide_index=True, width='stretch')
    st.subheader('Disponibilidad de valores documentales')
    availability = []
    for label, states, analytic_ids in (('Bruto', report.gross, report.analytic_gross), ('Neto', report.net, report.analytic_net)):
        availability.append({'Magnitud': label, **{STATUS[s]: len(ids) for s, ids in states},
                             'Disponible según C.1': len(analytic_ids),
                             'No disponible según C.1': len(report.document_ids) - len(analytic_ids)})
        for state, ids in states:
            buckets[f'{label} · {STATUS[state]}'] = ids
    st.dataframe(availability, hide_index=True, width='stretch')
    st.caption('Sin observación no demuestra que falte el importe en el PDF. Una observación no certificada '
               'no se convierte en cero. Estos recuentos no certifican moneda ni temporalidad económica.')
    st.subheader('Clasificación y revisión')
    st.caption('Categorías documentales según C.1. Un recuento cero no demuestra ausencia de ese tipo económico en el corpus.')
    st.dataframe([{'Categoría documental': CATEGORIES[c], 'Documentos': len(ids)}
                  for c, ids in report.categories], hide_index=True, width='stretch')
    for category, ids in report.categories:
        buckets['Categoría · ' + CATEGORIES[category]] = ids
    st.dataframe([{'Indicador': key, 'Documentos': len(buckets[key])} for key in (
        'Documentos multiversión', 'Incidencias para revisión', 'Restricciones locales de presentación')],
        hide_index=True, width='stretch')
    st.caption('Multiversión no significa conflicto sin resolver. Las incidencias son señales de contexto, '
               'clasificación o disponibilidad, no una cola de decisiones humanas ni una evaluación de relaciones. '
               'Las restricciones locales solo afectan a la representación: no eliminan documentos de esta cobertura.')
    st.subheader('Documentos que respaldan los recuentos')
    bucket = st.selectbox('Ver documentos que respaldan', list(buckets), key='coverage_bucket')
    selected = tuple(d for d in report.documents if d.document_id in buckets[bucket])
    if not selected:
        st.info('No hay documentos para este indicador. Los meses ausentes no tienen documentos asociados.')
        return
    st.dataframe([{'Documento': short_id(d.document_id), 'Empresa': d.company or 'Empresa sin asignar',
        'Periodo documental': format_period(d.year, d.month), 'Categoría': CATEGORIES[d.document.category],
        'Bruto': STATUS[d.gross], 'Neto': STATUS[d.net], 'Versiones': len(d.document.provenance),
        'Incidencias': '; '.join(REASONS[r] for r in d.review_reasons) or 'Sin incidencias detectadas en este alcance',
        'Restricción de presentación': 'Sí' if d.presentation_restricted else 'No'} for d in selected],
        hide_index=True, width='stretch')
    identity = st.selectbox('Documento individual', [None, *(d.document_id for d in selected)],
        format_func=lambda value: short_id(value) if value is not None else 'Selecciona un documento', key='coverage_document')
    if identity is not None:
        _details(next(d for d in selected if d.document_id == identity))
