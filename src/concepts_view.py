"""Readable evidence tables; version selection is local inspection only."""
from collections.abc import Sequence
from pathlib import Path

import streamlit as st

from src.canonical.values import ValueState
from src.classification_view import render_classification
from src.document_concepts import (
    REFERENCE_FIELDS,
    ConceptOccurrence,
    ExtractionConcepts,
    FactEvidence,
    load_document_concepts,
)
from src.gui_presentation import (
    VALUE_STATES,
    canonical_candidate_text,
    canonical_value_text,
    short_id,
)

_COLUMNS = {'codigo': 'Código original', 'concepto': 'Denominación original',
            'columna': 'Columna original', 'categoria': 'Categoría del parser',
            'unidades': 'Unidades', 'precio': 'Precio', 'porcentaje': 'Porcentaje',
            'base': 'Base documental', 'atraso': 'Atraso registrado', 'importe': 'Importe documental'}
_MONEY = {'importe', 'precio', 'base'}


def _text(evidence: FactEvidence | None, field: str) -> str:
    if evidence is None:
        return 'Denominación no registrada' if field == 'concepto' else 'Campo no registrado'
    return canonical_value_text(evidence.fact.value, monetary=field in _MONEY)


def concept_rows(concepts: Sequence[ConceptOccurrence]) -> list[dict[str, str]]:
    fields = [f for f in _COLUMNS if f in ('concepto', 'importe') or any(
        (e := c.get(f)) is not None and e.fact.value.state not in (
            ValueState.UNKNOWN, ValueState.NOT_EXTRACTED, ValueState.NOT_PRESENT,
            ValueState.NOT_APPLICABLE, ValueState.TECHNICAL_NULL) for c in concepts)]
    return [{**{_COLUMNS[f]: _text(c.get(f), f) for f in fields},
             'Estado del importe': VALUE_STATES[e.fact.value.state] if (e := c.get('importe')) is not None else 'Campo no registrado',
             'Versión documental': short_id(c.version_id)} for c in concepts]


def reference_rows(extraction: ExtractionConcepts) -> list[dict[str, str]]:
    rows = []
    for key, evidence in extraction.references:
        value = evidence.fact.value
        if value.state not in (ValueState.PRESENT, ValueState.UNRELIABLE):
            continue
        name = key.removeprefix('nomina.').removeprefix('payload/')
        rows.append({'Campo de referencia': REFERENCE_FIELDS[name],
                     'Valor documental': canonical_value_text(value, monetary=name != 'irpf_porcentaje'),
                     'Estado': VALUE_STATES[value.state]})
    return rows


def _trace(extraction: ExtractionConcepts) -> None:
    ids = {e.fact.fact_id for c in extraction.concepts for _, e in c.attributes}
    ids.update(e.fact.fact_id for _, e in extraction.references)
    with st.expander('Trazabilidad de conceptos y campos de referencia'):
        st.caption('Documento / versión / extracción completos')
        st.code('\n'.join((extraction.document_id, extraction.version_id, extraction.extraction_id)), language=None)
        st.dataframe([{'Clave original': e.fact.fact_key, 'Hecho completo': e.fact.fact_id,
                       'Estado canónico': e.fact.value.state.value,
                       'Valor o candidato original': canonical_candidate_text(e.fact.value),
                       'Motivo': e.fact.value.reason_code or 'Sin motivo registrado',
                       'Páginas del hecho': ', '.join(map(str, e.pages)) or 'No registradas'}
                      for e in extraction.facts if e.fact.fact_id in ids], hide_index=True)


def render_concepts(database: Path, document_id: str) -> None:
    document = load_document_concepts(database, document_id)
    extractions = document.extractions
    versions = document.version_ids
    st.subheader('Desglose documental de conceptos')
    st.caption('Partidas documentales, no nuevas observaciones certificadas. No se suman al bruto ni al neto. '
               'Los importes sin código de moneda conservan moneda desconocida; unidades no implica días u horas.')
    if not versions:
        st.info('No hay versiones documentales disponibles para inspeccionar.')
    version = versions[0] if len(versions) == 1 else None
    if len(versions) > 1:
        st.info('Elige una versión para leer su desglose. Esta selección no cambia resoluciones ni los totales certificados.')
        version = st.selectbox('Versión para consultar', [None, *versions],
            format_func=lambda v: 'Selecciona una versión' if v is None else short_id(v),
            key='concept-version-' + document_id, persist_state='session')
    selected = [e for e in extractions if e.version_id == version]
    if version is not None and not any(e.concepts for e in selected):
        st.info('El desglose por conceptos no está disponible en SQLite para esta versión. '
                'Se muestran los campos de referencia existentes, sin reconstruir partidas.')
    for extraction in selected:
        if len(selected) > 1:
            st.caption('Extracción ' + short_id(extraction.extraction_id) + ' · Se consulta por separado.')
        for group in ('Devengos', 'Deducciones', 'Otros / grupo desconocido'):
            concepts = [c for c in extraction.concepts if c.group == group]
            if concepts:
                st.markdown('**' + group + '**')
                st.dataframe(concept_rows(concepts), hide_index=True, column_config={
                    name: st.column_config.TextColumn(alignment='right')
                    for name in ('Importe documental', 'Unidades', 'Precio', 'Porcentaje', 'Base documental')})
        references = reference_rows(extraction)
        if references:
            st.markdown('**Datos complementarios y de referencia**')
            st.caption('Pueden repetir partidas del desglose. No son pagos adicionales. '
                       'Una prorrata informativa o una base no se interpreta como devengo.')
            st.dataframe(references, hide_index=True, column_config={
                'Valor documental': st.column_config.TextColumn(alignment='right')})
        render_classification(extraction)
        _trace(extraction)
    with st.expander('Visor completo de hechos documentales · investigación avanzada'):
        for extraction in extractions:
            st.caption('Versión ' + short_id(extraction.version_id) + ' · Extracción ' + short_id(extraction.extraction_id))
            st.dataframe([{'Clave original': e.fact.fact_key, 'Valor o estado': canonical_value_text(e.fact.value),
                           'Hecho completo': e.fact.fact_id, 'Estado canónico': e.fact.value.state.value,
                           'Motivo': e.fact.value.reason_code or 'Sin motivo registrado',
                           'Páginas del hecho': ', '.join(map(str, e.pages)) or 'No registradas'}
                          for e in extraction.facts], hide_index=True)
