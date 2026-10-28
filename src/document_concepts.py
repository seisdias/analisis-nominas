"""Typed read projection of documentary occurrences; no economic interpretation."""
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.canonical.facts import DocumentaryFact
from src.canonical.values import ValueState
from src.canonical_inspection import open_inspector

REFERENCE_FIELDS = {
    'salario_base': 'Salario base', 'plus_convenio': 'Plus convenio',
    'complementos': 'Complementos (campo escalar)',
    'prorrata_pagas_extra': 'Prorrata de extras (campo de referencia)',
    'pror_otros': 'PROR.OTROS (significado no ampliado)',
    'irpf_porcentaje': 'Tipo de IRPF', 'irpf_importe': 'Importe IRPF',
    'descuento_seguridad_social': 'Descuento Seguridad Social',
    'otras_deducciones': 'Otras deducciones (campo escalar)', 'total_deducir': 'Total a deducir',
    'base_ss_comunes': 'Base de contingencias comunes', 'base_at_ep': 'Base AT/EP',
    'base_irpf': 'Base IRPF', 'base_irpf_pie': 'Base IRPF del pie',
    'base_sujeta_retencion_irpf': 'Base sujeta a retención IRPF',
    'base_irpf_especie': 'Base IRPF en especie',
}
_CONCEPT = re.compile(r'(nomina\.conceptos\.[0-9a-f]{64}\.(?:0|[1-9][0-9]*))\.([a-z_]+)$'
                      r'|(payload/conceptos/(?:0|[1-9][0-9]*))/([a-z_]+)$')


@dataclass(frozen=True, slots=True)
class FactEvidence:
    fact: DocumentaryFact
    pages: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ConceptOccurrence:
    document_id: str
    version_id: str
    extraction_id: str
    occurrence: str
    attributes: tuple[tuple[str, FactEvidence], ...]

    def get(self, field: str) -> FactEvidence | None:
        return next((e for name, e in self.attributes if name == field), None)

    @property
    def group(self) -> str:
        evidence = self.get('columna')
        if evidence and evidence.fact.value.state == ValueState.PRESENT:
            return {'devengos': 'Devengos', 'deducciones': 'Deducciones'}.get(
                str(evidence.fact.value.value), 'Otros / grupo desconocido')
        return 'Otros / grupo desconocido'


@dataclass(frozen=True, slots=True)
class ExtractionConcepts:
    document_id: str
    version_id: str
    extraction_id: str
    concepts: tuple[ConceptOccurrence, ...]
    references: tuple[tuple[str, FactEvidence], ...]
    facts: tuple[FactEvidence, ...]


def project_extraction(document_id: str, version_id: str, extraction_id: str,
                       facts: Sequence[DocumentaryFact], *,
                       pages: Mapping[str, tuple[int, ...]] | None = None) -> ExtractionConcepts:
    """Group by full occurrence prefix within exactly one extraction/version."""
    unique: dict[str, DocumentaryFact] = {}
    for fact in facts:
        if fact.extraction_id != extraction_id:
            raise ValueError('Mixed extraction facts')
        previous = unique.get(fact.fact_key)
        if previous is not None and previous != fact:
            raise ValueError('Conflicting duplicate fact')
        unique[fact.fact_key] = fact
    grouped: dict[str, list[tuple[str, FactEvidence]]] = {}
    references = []
    evidence = []
    for key, fact in sorted(unique.items()):
        item = FactEvidence(fact, tuple(sorted(set((pages or {}).get(fact.fact_id, ())))))
        evidence.append(item)
        match = _CONCEPT.fullmatch(key)
        if match:
            prefix, field = (match[1], match[2]) if match[1] else (match[3], match[4])
            grouped.setdefault(prefix, []).append((field, item))
        elif key in {p + name for name in REFERENCE_FIELDS for p in ('nomina.', 'payload/')}:
            references.append((key, item))
    return ExtractionConcepts(document_id, version_id, extraction_id,
        tuple(ConceptOccurrence(document_id, version_id, extraction_id, prefix, tuple(attrs))
              for prefix, attrs in sorted(grouped.items())), tuple(references), tuple(evidence))


@dataclass(frozen=True, slots=True)
class DocumentConcepts:
    document_id: str
    version_ids: tuple[str, ...]
    extractions: tuple[ExtractionConcepts, ...]


def load_document_concepts(database: Path, document_id: str) -> DocumentConcepts:
    """Complete read-only document snapshot, including empty extractions and all versions."""
    result = []
    with open_inspector(database) as inspector:
        detail = inspector.document(document_id)
        for version in detail['versions']:
            for extraction in version['extractions']:
                facts = inspector.extraction_facts(extraction.extraction_id)
                pages = {f.fact_id: tuple(p.page_number for p in inspector.fact_pages(f.fact_id)) for f in facts}
                result.append(project_extraction(document_id, version['version'].version_id,
                                                 extraction.extraction_id, facts, pages=pages))
    return DocumentConcepts(document_id, tuple(v['version'].version_id for v in detail['versions']), tuple(result))
