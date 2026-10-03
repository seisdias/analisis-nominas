"""Existing parser/adapter bindings. No company-specific economic interpretation."""

import json
from dataclasses import dataclass
from importlib.resources import files
from io import BytesIO
from typing import Any

from scripts.ingest_alten import is_certificate
from src.alten_canonical import integrate_alten
from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    VersionPage,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.evidence import FileLocation, SourceFile
from src.canonical.facts import DocumentaryFact, FactPage
from src.canonical.serialization import canonical_sha256, sha256_bytes
from src.economic_mapping import evaluate_direct_totals
from src.models.nomina import Nomina
from src.nomina_facts import adapt_nomina
from src.parsers.alten_parser import AltenParser
from src.parsers.base import BaseParser
from src.persistence.relations import RelationRepository
from src.services.ingestion_service import extract_pdf_document


def _revision(parser: BaseParser) -> str:
    paths = ['canonical_ingestion.py', 'ingestion_processors.py', 'nomina_facts.py',
             'economic_mapping.py', 'alten_canonical.py', 'extraction.py',
             'services/ingestion_service.py', 'parsers/base.py', 'models/nomina.py',
             'models/documento_laboral.py', 'parsers/' + type(parser).__module__.rsplit('.', 1)[-1] + '.py']
    return canonical_sha256({p: sha256_bytes(files('src').joinpath(p).read_bytes()) for p in paths})


@dataclass(frozen=True)
class PayrollUnit:
    segment: str
    model: Nomina
    pages: tuple[int, ...]


@dataclass
class OrdinaryPDF:
    page_count: int | None
    units: tuple[PayrollUnit, ...]
    revision: str
    processor_name: str
    skip_reason: str | None = None

    def persist(self, repo: RelationRepository, file: SourceFile, location: FileLocation, stamp: str) -> None:
        if not self.units or len({u.segment for u in self.units}) != len(self.units):
            raise ValueError('Nonempty distinct documentary units required')
        for unit in sorted(self.units, key=lambda u: (u.segment, u.pages)):
            model = unit.model
            if not model.es_procesable:
                raise ValueError('Model is not processable')
            # Physical origin + explicit segment, never employer/month alone.
            origin = canonical_sha256({'path': location.relative_path, 'sha256': file.sha256, 'segment': unit.segment})
            doc = LogicalDocument(document_id(location.corpus_id, origin), location.corpus_id, None,
                                  model.tipo.value, origin, stamp)
            repo.register_document(doc)
            version = DocumentVersion(version_id(doc.document_id, file.file_id, unit.segment),
                                      doc.document_id, file.file_id, unit.segment, stamp)
            repo.register_version(version)
            for ordinal, page in enumerate(unit.pages):
                repo.associate_page(VersionPage(version.version_id, page, ordinal))
            drafts = tuple(sorted(adapt_nomina(model), key=lambda d: d.fact_key))
            config = canonical_sha256({'adapter': 'nomina-facts/v1', 'filename': location.original_filename})
            content = canonical_sha256({d.fact_key: d.value for d in drafts})
            extraction = Extraction(extraction_id(version.version_id, self.processor_name, self.revision, config),
                                    version.version_id, self.processor_name, self.revision, config, content, stamp)
            repo.register_extraction(extraction)
            facts = tuple(DocumentaryFact.from_draft(extraction.extraction_id, d, created_at=stamp) for d in drafts)
            for fact in facts:
                repo.register_fact(fact)
                # A multi-page parser offers document scope, not exact field pages.
                if len(unit.pages) == 1:
                    repo.associate_fact_page(FactPage(fact.fact_id, unit.pages[0]))
            interpretation = evaluate_direct_totals(doc.document_id, facts, created_at=stamp)
            repo.register_rule(interpretation.rule)
            repo.register_assessment(interpretation.assessment)
            for evidence in interpretation.observations:
                repo.register_observation(evidence.observation, evidence.fact_ids)


class OrdinaryProcessor:
    def __init__(self, parser: BaseParser) -> None:
        if isinstance(parser, AltenParser):
            raise ValueError('ALTEN requires its documentary processor')
        self.parser = parser
        self.revision = _revision(parser)

    def prepare(self, data: bytes, filename: str) -> OrdinaryPDF:
        document = extract_pdf_document(BytesIO(data))
        count = len(document.pages or ())
        if not document.text.strip():
            return OrdinaryPDF(count, (), self.revision, type(self.parser).__name__, 'no_extractable_text')
        model = self.parser.parse_extracted(document, filename=filename)
        return OrdinaryPDF(count, (PayrollUnit('whole_pdf', model, tuple(range(1, count + 1))),),
                           self.revision, type(self.parser).__name__)


@dataclass
class AltenPDF:
    page_count: int | None
    periods: tuple[dict[str, Any], ...]
    versions: tuple[dict[str, Any], ...]
    skip_reason: str | None = None

    def persist(self, repo: RelationRepository, file: SourceFile, location: FileLocation, stamp: str) -> None:
        integrate_alten(repo, location.corpus_id, self.periods, self.versions, [(file, location)], created_at=stamp)


class AltenProcessor:
    def __init__(self) -> None:
        self.parser = AltenParser()
        self.revision = canonical_sha256({'parser': _revision(self.parser),
            'certificate_filter': sha256_bytes(files('scripts').joinpath('ingest_alten.py').read_bytes())})

    def prepare(self, data: bytes, filename: str) -> AltenPDF:
        document = extract_pdf_document(BytesIO(data))
        count = len(document.pages or ())
        if not document.text.strip():
            return AltenPDF(count, (), (), 'no_extractable_text')
        if is_certificate(document):
            return AltenPDF(count, (), (), 'annual_certificate')
        models = self.parser.parse_pages(document)
        digest = sha256_bytes(data)
        periods, versions = {}, []
        for page, model in enumerate(models, 1):
            fields = {'cif': model.cif, 'fecha_inicio': model.fecha_inicio,
                      'fecha_fin': model.fecha_fin, 'tipo': model.tipo.value}
            if model.fecha_inicio is None or model.fecha_fin is None:
                raise ValueError('ALTEN lacks documentary period dates')
            key = '|'.join(str(fields[k]) for k in ('cif', 'fecha_inicio', 'fecha_fin', 'tipo'))
            periods[key] = {**fields, 'period_key': key, 'resolution_status': 'UNRESOLVED'}
            versions.append({'period_key': key, 'version_key': f'sha256:{digest}:page:{page}',
                             'pdf_sha256': digest, 'page_number': page, 'source_filename': filename,
                             'payload': json.dumps(model.to_dict(), ensure_ascii=False, sort_keys=True,
                                                   separators=(',', ':'), allow_nan=False)})
        return AltenPDF(count, tuple(periods.values()), tuple(versions))
