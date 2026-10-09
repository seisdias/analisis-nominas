"""Immutable registered relational context, not an economic decision.

Completeness comes from the loader's exhaustive transactional reads, not from a
caller-supplied flag or this type's mere existence. A snapshot may contain cycles,
competing interpretations and unresolved assertions. It proves nothing about
unrecorded real-world relationships and never designates an active version.
"""
from dataclasses import dataclass
from typing import Literal

from src.canonical.documents import DocumentVersion, Extraction, LogicalDocument, VersionPage
from src.canonical.economics import Assessment, ObservationEvidence, Rule
from src.canonical.evidence import SourceFile
from src.canonical.facts import DocumentaryFact, FactPage
from src.canonical.relations import DocumentRelation, ObservationRelation


@dataclass(frozen=True, slots=True)
class CandidacyRelationalSnapshot:
    """Document/observation connected component, with every assessment sibling.

    All versions of reached documents are included, including uninterpreted ones.
    Documentary support covers assessment inputs, their extractions/files/pages
    and rules (also relation rules). Unreferenced extraction payloads are outside
    this scope. Collections are tuples ordered by IDs (pages by their own keys).
    """
    target: ObservationEvidence
    observations: tuple[ObservationEvidence, ...]
    assessments: tuple[Assessment, ...]
    documents: tuple[LogicalDocument, ...]
    versions: tuple[DocumentVersion, ...]
    document_relations: tuple[DocumentRelation, ...]
    observation_relations: tuple[ObservationRelation, ...]
    facts: tuple[DocumentaryFact, ...]
    extractions: tuple[Extraction, ...]
    rules: tuple[Rule, ...]
    source_files: tuple[SourceFile, ...]
    version_pages: tuple[VersionPage, ...]
    fact_pages: tuple[FactPage, ...]
    contract: Literal['candidacy-relational-snapshot/v1'] = 'candidacy-relational-snapshot/v1'
    scope: Literal['registered-document-observation-closure'] = 'registered-document-observation-closure'

    def __post_init__(self) -> None:
        for collection in (self.observations, self.assessments, self.documents, self.versions,
                           self.document_relations, self.observation_relations, self.facts,
                           self.extractions, self.rules, self.source_files, self.version_pages,
                           self.fact_pages):
            if type(collection) is not tuple:
                raise TypeError('Snapshot collections must be immutable tuples')
