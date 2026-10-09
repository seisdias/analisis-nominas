"""Read a registered relational closure in one owned read-only database snapshot."""
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

from src.canonical.documents import DocumentVersion, Extraction, LogicalDocument, VersionPage
from src.canonical.economics import Assessment, ObservationEvidence, Rule, fact_fingerprint
from src.canonical.evidence import SourceFile
from src.canonical.facts import DocumentaryFact, FactPage
from src.canonical.relational_snapshot import CandidacyRelationalSnapshot
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.persistence import CanonicalSQLiteError, open_database
from src.persistence.relations import RelationRepository


class SnapshotFailure(StrEnum):
    MISSING_REFERENCE = 'snapshot.missing_reference'
    INVALID_REFERENCE = 'snapshot.invalid_reference'
    READ_FAILED = 'snapshot.read_failed'


class CandidacySnapshotError(ValueError):
    def __init__(self, reason: SnapshotFailure) -> None:
        self.reason = reason
        super().__init__(reason.value)


T = TypeVar('T')


def _require(value: T | None) -> T:
    if value is None:
        raise CandidacySnapshotError(SnapshotFailure.MISSING_REFERENCE)
    return value


def _valid(condition: bool) -> None:
    if not condition:
        raise CandidacySnapshotError(SnapshotFailure.INVALID_REFERENCE)


class CandidacySnapshotLoader:
    def __init__(self, database: str | Path) -> None:
        self._database = database

    def load_candidacy_snapshot(self, observation_id: str) -> CandidacyRelationalSnapshot:
        """Own the read transaction; no externally asserted completeness is accepted.

        Verification opens mode=ro/query_only and retains a BEGIN snapshot through
        every read. No selection service, readiness evaluation or write is called.
        """
        try:
            with open_database(self._database, mode='verify') as db:
                _valid(db.status.current_version == 8 and not db.status.pending_versions)
                return _load(RelationRepository(db.connection), observation_id)
        except CandidacySnapshotError:
            raise
        except (ValueError, TypeError, AssertionError) as error:
            raise CandidacySnapshotError(SnapshotFailure.INVALID_REFERENCE) from error
        except (OSError, sqlite3.Error, CanonicalSQLiteError) as error:
            raise CandidacySnapshotError(SnapshotFailure.READ_FAILED) from error


def _load(repo: RelationRepository, observation_id: str) -> CandidacyRelationalSnapshot:
    target = _require(repo.get_observation(observation_id))
    target_assessment = _require(repo.get_assessment(target.observation.assessment_id))
    # Exhaustive reads: missing edges cannot be concealed by a caller's tuple.
    all_document_relations = repo.list_document_relations()
    all_observation_relations = repo.list_observation_relations()
    all_assessments = repo.list_assessments()
    observations: dict[str, ObservationEvidence] = {}
    assessments: dict[str, Assessment] = {}
    documents: dict[str, LogicalDocument] = {}
    versions: dict[str, DocumentVersion] = {}
    facts: dict[str, DocumentaryFact] = {}
    extractions: dict[str, Extraction] = {}
    rules: dict[str, Rule] = {}
    source_files: dict[str, SourceFile] = {}
    version_pages: dict[tuple[str, int], VersionPage] = {}
    fact_pages: dict[tuple[str, int], FactPage] = {}
    document_relations: dict[str, DocumentRelation] = {}
    observation_relations: dict[str, ObservationRelation] = {}
    pending = {target_assessment.document_id}
    visited: set[str] = set()
    while pending:
        identity = min(pending)
        pending.remove(identity)
        if identity in visited:
            continue
        visited.add(identity)
        documents[identity] = _require(repo.get_document(identity))
        for version in repo.get_document_versions(identity):
            _valid(version.document_id == identity)
            versions[version.version_id] = version
            file = _require(repo.get_source_file(version.file_id))
            source_files[file.file_id] = file
            for page in repo.get_version_pages(version.version_id):
                _valid(file.page_count is None or page.page_number <= file.page_count)
                version_pages[(page.version_id, page.ordinal)] = page
        for assessment in all_assessments:
            if assessment.document_id != identity:
                continue
            assessments[assessment.assessment_id] = assessment
            rules[assessment.rule_id] = _require(repo.get_rule(assessment.rule_id))
            for item in assessment.inputs:
                fact = _require(repo.get_fact(item.fact_id))
                _valid(fact_fingerprint(fact) == item.content_hash)
                extraction = _require(repo.get_extraction(fact.extraction_id))
                version = _require(versions.get(extraction.version_id))
                _valid(version.document_id == identity)
                facts[fact.fact_id] = fact
                extractions[extraction.extraction_id] = extraction
                known_pages = {p.page_number for p in version_pages.values() if p.version_id == version.version_id}
                for reference in repo.get_fact_page_references(fact.fact_id):
                    _valid(reference.version_id == extraction.version_id)
                    _valid(reference.page_number in known_pages)
                    fact_page = FactPage(reference.fact_id, reference.page_number)
                    fact_pages[(fact_page.fact_id, fact_page.page_number)] = fact_page
            for evidence in repo.get_observations(assessment.assessment_id):
                _valid(evidence.observation.assessment_id == assessment.assessment_id)
                _valid(set(evidence.fact_ids) <= {i.fact_id for i in assessment.inputs})
                observations[evidence.observation.observation_id] = evidence
                for relation in all_observation_relations:
                    endpoints = (relation.source_observation_id, relation.target_observation_id)
                    if evidence.observation.observation_id not in endpoints:
                        continue
                    observation_relations[relation.relation_id] = relation
                    for endpoint in endpoints:
                        other = _require(repo.get_observation(endpoint))
                        owner = _require(repo.get_assessment(other.observation.assessment_id))
                        pending.add(owner.document_id)
        for relation_doc in all_document_relations:
            endpoints_doc = (relation_doc.source_document_id, relation_doc.target_document_id)
            if identity in endpoints_doc:
                document_relations[relation_doc.relation_id] = relation_doc
                pending.update(endpoints_doc)
    _valid(observations.get(observation_id) == target)
    for relation in observation_relations.values():
        _valid(relation.source_observation_id in observations and relation.target_observation_id in observations)
    for relation_doc in document_relations.values():
        _valid(relation_doc.source_document_id in documents and relation_doc.target_document_id in documents)
    relation_rule_ids = ({r.rule_id for r in document_relations.values() if r.rule_id is not None}
                         | {r.rule_id for r in observation_relations.values() if r.rule_id is not None})
    for rule_id in sorted(relation_rule_ids):
        rules[rule_id] = _require(repo.get_rule(rule_id))
    return CandidacyRelationalSnapshot(
        target=target,
        observations=tuple(observations[k] for k in sorted(observations)),
        assessments=tuple(assessments[k] for k in sorted(assessments)),
        documents=tuple(documents[k] for k in sorted(documents)),
        versions=tuple(versions[k] for k in sorted(versions)),
        document_relations=tuple(document_relations[k] for k in sorted(document_relations)),
        observation_relations=tuple(observation_relations[k] for k in sorted(observation_relations)),
        facts=tuple(facts[k] for k in sorted(facts)),
        extractions=tuple(extractions[k] for k in sorted(extractions)),
        rules=tuple(rules[k] for k in sorted(rules)),
        source_files=tuple(source_files[k] for k in sorted(source_files)),
        version_pages=tuple(version_pages[k] for k in sorted(version_pages)),
        fact_pages=tuple(fact_pages[k] for k in sorted(fact_pages)),
    )
