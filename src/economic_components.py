"""Conservative B1 presentation of individual facts, never certified observations."""
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.analytic_dataset import AnalyticDocument, DocumentCategory
from src.canonical.values import ExactDecimal, ValueState
from src.document_concepts import ConceptOccurrence, DocumentConcepts, FactEvidence
from src.gui_presentation import canonical_value_text, format_period

CONTRACT = 'documentary-components/d2.3-b1-v1'
# Exact documentary tuples, scoped to their original extractor. No label similarity,
# amount/date/company rules, scalar fallback, or cross-company equivalence.
_RULES = {
    ('InecoParser','9032','paga extra vera','paga_extra_incluida','false'): 'Extra de verano incluida',
    ('InecoParser','9033','paga extra navi','paga_extra_incluida','false'): 'Extra de Navidad incluida',
    ('InecoParser','9RPE','r. pext dic 2012','regularizaciones','false'): 'Ajustes de extras',
    ('ExcelticParser','1','P.P.EXTRA','paga_extra_incluida','false'): 'Prorratas de extras',
    ('AltranParser','R1X','Parte Proporcional Pagas Extras','paga_extra_incluida','false'): 'Prorratas de extras',
    ('alten-legacy-evidence','9016','P.P. Extra Verano','paga_extra_incluida','false'): 'Prorratas de extras',
    ('alten-legacy-evidence','9017','P.P. Extra Navidad','paga_extra_incluida','false'): 'Prorratas de extras',
    ('alten-legacy-evidence','9122','Bono','bono','false'): 'Bonus / variable',
    ('alten-legacy-evidence','9030','Bono/Variable','variable','false'): 'Bonus / variable',
}
COMPONENTS = tuple(dict.fromkeys(_RULES.values()))


@dataclass(frozen=True)
class ComponentPoint:
    component: str
    company: str
    period: tuple[int, int]
    occurrence: ConceptOccurrence
    amount: FactEvidence
    extractor_name: str
    extractor_revision: str


@dataclass(frozen=True)
class ComponentProjection:
    points: tuple[ComponentPoint, ...]
    omitted: tuple[tuple[str, str], ...]


def documentary_block(doc: AnalyticDocument, blocked: Mapping[str, str]) -> str | None:
    if doc.document_id in blocked:
        return blocked[doc.document_id]
    if len(doc.provenance) != 1:
        return 'Multiversión o versión ausente: conceptos sin selección autorizada'
    if doc.category != DocumentCategory.ORDINARY or doc.classification_document_id != doc.document_id:
        return 'Sin clasificación ordinaria inequívoca para componentes internos'
    if not doc.company_text or not doc.documentary_period:
        return 'Empresa o periodo documental incompleto'
    year, month = doc.documentary_period
    if not (1 <= year <= 9999 and 1 <= month <= 12):
        return 'Periodo documental inválido'
    return None


def _text(c: ConceptOccurrence, field: str) -> str:
    e = c.get(field)
    return str(e.fact.value.value) if e and e.fact.value.state == ValueState.PRESENT else ""


def project_components(documents: Sequence[AnalyticDocument], sources: Mapping[str, DocumentConcepts],
                       blocked: Mapping[str, str]) -> ComponentProjection:
    """Full-context restrictions precede visibility. Never choose versions/extractions."""
    points = []
    omitted: set[tuple[str, str]] = set()
    counts = Counter(d.document_id for d in documents)
    for doc in sorted(documents, key=lambda d: d.document_id):
        identity = doc.document_id
        reason = documentary_block(doc, blocked)
        if counts[identity] != 1:
            reason = 'Identidad documental duplicada'
        if reason:
            omitted.add((identity, reason))
            continue
        source = sources.get(identity)
        if (source is None or source.document_id != identity
                or source.version_ids != (doc.provenance[0].version_id,)):
            omitted.add((identity, 'Procedencia documental incompleta o incompatible'))
            continue
        extractions = [e for e in source.extractions if e.concepts]
        if len(extractions) != 1:
            omitted.add((identity, 'Desglose no disponible' if not extractions else
                         'Varias extracciones con conceptos: sin selección autorizada'))
            continue
        extraction = extractions[0]
        if (extraction.extraction_id not in doc.provenance[0].extraction_ids
                or extraction.version_id != source.version_ids[0]
                or extraction.document_id != identity
                or len({c.occurrence.split('conceptos')[0] for c in extraction.concepts}) != 1):
            omitted.add((identity, 'Trazabilidad o vocabulario de conceptos no inequívoco'))
            continue
        matched = False
        for c in sorted(extraction.concepts, key=lambda c: c.occurrence):
            component = _RULES.get((extraction.extractor_name, _text(c,'codigo'), _text(c,'concepto'),
                                   _text(c,'categoria'), _text(c,'atraso')))
            if component is None or _text(c,'columna') != 'devengos':
                continue
            matched = True
            amount = c.get('importe')
            if amount is None or amount.fact.value.state != ValueState.PRESENT or not isinstance(amount.fact.value.value, ExactDecimal):
                omitted.add((identity, 'Concepto identificado sin importe disponible y fiable'))
                continue
            if amount.fact.value.currency is not None and amount.fact.value.currency.code != 'EUR':
                omitted.add((identity, 'Concepto con divisa explícita incompatible con EUR'))
                continue
            if (c.document_id, c.version_id, c.extraction_id) != (identity, extraction.version_id, extraction.extraction_id):
                omitted.add((identity, 'Trazabilidad de ocurrencia incompatible'))
                continue
            assert doc.company_text is not None and doc.documentary_period is not None
            points.append(ComponentPoint(component, doc.company_text, doc.documentary_period, c, amount,
                                         extraction.extractor_name, extraction.extractor_revision))
        if not matched:
            omitted.add((identity, 'Sin correspondencias explícitas B1; consulta el desglose en la ficha'))
    return ComponentProjection(tuple(points), tuple(sorted(omitted)))


def component_rows(points: Sequence[ComponentPoint]) -> list[dict[str, Any]]:
    rows = []
    for p in points:
        c, value = p.occurrence, p.amount.fact.value
        assert isinstance(value.value, ExactDecimal)
        rows.append({'Fecha': f'{p.period[0]:04d}-{p.period[1]:02d}-01',
            'Periodo del documento': format_period(*p.period), 'Empresa': p.company, 'Componente': p.component,
            'Importe': float(value.value.to_decimal()), 'Importe exacto': canonical_value_text(value, monetary=True),
            'Moneda canónica': value.currency.code if value.currency else 'No acreditada',
            'Documento': c.document_id, 'Versión': c.version_id, 'Extracción': c.extraction_id,
            'Ocurrencia': c.occurrence, 'Hecho': p.amount.fact.fact_id, 'Clave original': p.amount.fact.fact_key,
            'Etiqueta original': _text(c,'concepto'), 'Código original': _text(c,'codigo'),
            'Columna documental': _text(c,'columna'), 'Categoría original': _text(c,'categoria'),
            'Estado': 'Disponible', 'Páginas': ', '.join(map(str,p.amount.pages)) or 'No registradas',
            'Extractor': p.extractor_name, 'Revisión': p.extractor_revision, 'Contrato visual': CONTRACT})
    return rows
