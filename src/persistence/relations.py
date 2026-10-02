"""Persistence of two explicit relation types and typed candidate-selection reads."""

from dataclasses import fields, replace

from src.canonical.economics import Assessment, ObservationEvidence
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.relations import DocumentRelation, ObservationRelation
from src.persistence.economics import EconomicRepository
from src.persistence.evidence import WriteOutcome

_DOCUMENT_COLUMNS = ('relation_id, source_document_id, target_document_id, relation_type, '
                     'rule_id, reason_code, created_at')
_OBSERVATION_COLUMNS = ('relation_id, source_observation_id, target_observation_id, relation_type, '
                        'rule_id, reason_code, created_at')


class RelationRepository(EconomicRepository):
    def register_document_relation(self, relation: DocumentRelation) -> WriteOutcome:
        with self.transaction():
            old = self.get_document_relation(relation.relation_id)
            if old is not None:
                if replace(relation, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting document relation provenance')
                return WriteOutcome.IDENTICAL
            self._insert('document_relations', _DOCUMENT_COLUMNS,
                         tuple(getattr(relation, f.name) for f in fields(relation)))
            return WriteOutcome.CREATED

    def get_document_relation(self, relation_id: str) -> DocumentRelation | None:
        row = self._connection.execute('SELECT ' + _DOCUMENT_COLUMNS + ' FROM document_relations WHERE relation_id=?',
                                       (relation_id,)).fetchone()
        return DocumentRelation(*row) if row is not None else None

    def list_document_relations(self) -> tuple[DocumentRelation, ...]:
        rows = self._connection.execute('SELECT ' + _DOCUMENT_COLUMNS + ' FROM document_relations ORDER BY relation_id')
        return tuple(DocumentRelation(*row) for row in rows)

    def register_observation_relation(self, relation: ObservationRelation) -> WriteOutcome:
        with self.transaction():
            old = self.get_observation_relation(relation.relation_id)
            if old is not None:
                if replace(relation, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting observation relation provenance')
                return WriteOutcome.IDENTICAL
            self._insert('observation_relations', _OBSERVATION_COLUMNS,
                         tuple(getattr(relation, f.name) for f in fields(relation)))
            return WriteOutcome.CREATED

    def get_observation_relation(self, relation_id: str) -> ObservationRelation | None:
        row = self._connection.execute('SELECT ' + _OBSERVATION_COLUMNS + ' FROM observation_relations WHERE relation_id=?',
                                       (relation_id,)).fetchone()
        return ObservationRelation(*row) if row is not None else None

    def list_observation_relations(self) -> tuple[ObservationRelation, ...]:
        rows = self._connection.execute('SELECT ' + _OBSERVATION_COLUMNS + ' FROM observation_relations ORDER BY relation_id')
        return tuple(ObservationRelation(*row) for row in rows)

    def list_assessments(self) -> tuple[Assessment, ...]:
        ids = self._connection.execute('SELECT assessment_id FROM assessments ORDER BY assessment_id').fetchall()
        result = []
        for (identity,) in ids:
            assessment = self.get_assessment(identity)
            if assessment is None:
                raise ValueError('Assessment disappeared during retrieval')
            result.append(assessment)
        return tuple(result)

    def candidate_versions(self, assessment: Assessment, evidence: ObservationEvidence) -> tuple[str, ...]:
        """Verify input content/ownership and return source versions, never pick one."""
        if self.get_rule(assessment.rule_id) is None:
            raise ValueError('Assessment has no recorded rule')
        if evidence.observation.assessment_id != assessment.assessment_id:
            raise ValueError('Observation belongs to another assessment')
        if not evidence.fact_ids or not set(evidence.fact_ids) <= {i.fact_id for i in assessment.inputs}:
            raise ValueError('Insufficient observation support')
        self._validate_inputs(assessment)
        versions = set()
        for item in assessment.inputs:
            row = self._connection.execute(
                'SELECT e.version_id FROM documentary_facts f JOIN extractions e '
                'ON e.extraction_id=f.extraction_id WHERE f.fact_id=?', (item.fact_id,),
            ).fetchone()
            if row is None:
                raise ValueError('Missing input source version')
            versions.add(row[0])
        return tuple(sorted(versions))
