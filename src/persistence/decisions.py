"""Storage and evidence snapshots for portable manual decisions."""

from dataclasses import fields, replace

from src.canonical.decisions import ManualDecision, encode_decisions
from src.canonical.documents import DocumentVersion, Extraction, LogicalDocument, VersionPage
from src.canonical.economics import fact_fingerprint
from src.canonical.evidence import Corpus, SourceFile
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.serialization import canonical_sha256
from src.persistence.evidence import WriteOutcome
from src.persistence.relations import RelationRepository

_COLUMNS = ', '.join(ManualDecision.__dataclass_fields__)


class DecisionPreconditionConflict(ReproducibilityConflict):
    """Fail closed: the rebuild may not be published or its decisions applied."""

    publication_blocked = True

    def __init__(self, target_id: str, reason: str) -> None:
        self.target_id = target_id
        self.reason = reason
        super().__init__(f'Manual decision precondition failed: {reason} ({target_id})')


def _record(record: DocumentVersion | Extraction | LogicalDocument | VersionPage | Corpus | SourceFile | None) -> dict[str, object]:
    if record is None:
        raise ValueError('Missing documentary provenance')
    # Preserve semantic metadata; operational timestamps do not change evidence.
    return {f.name: (str(value) if isinstance(value := getattr(record, f.name), str) else value)
            for f in fields(record) if f.name not in {'created_at', 'first_seen_at'}}


class DecisionRepository(RelationRepository):
    def precondition_hash(self, target_type: str, target_id: str) -> str:
        """v1 acknowledgement scope: exact fact + extraction peers + physical chain.

        Includes all facts of the extraction, known pages, PDF metadata/availability,
        document identity and corpus/person assignment. Excludes ingestion timestamps,
        physical locations, interpretations and unrelated documents. Acknowledgement
        is about this evidence, never approval of a logical document's winning version.
        """
        if target_type != 'documentary_fact':
            raise ValueError('Unsupported precondition target type')
        with self.transaction():
            fact = self.get_fact(target_id)
            if fact is None:
                raise DecisionPreconditionConflict(target_id, 'target_missing')
            extraction = self.get_extraction(fact.extraction_id)
            assert extraction is not None
            version = self.get_version(extraction.version_id)
            assert version is not None
            document = self.get_document(version.document_id)
            assert document is not None
            corpus = self.get_corpus(document.corpus_id)
            content = {
                'contract': 'manual-fact-evidence/v1', 'target': str(target_id),
                'facts': [{'fingerprint': fact_fingerprint(item),
                           'pages': [p.page_number for p in self.get_fact_pages(item.fact_id)]}
                          for item in self.get_extraction_facts(fact.extraction_id)],
                'extraction': _record(extraction), 'version': _record(version),
                'document': _record(document), 'corpus': _record(corpus),
                'source_file': _record(self.get_source_file(version.file_id)),
                'version_pages': [_record(p) for p in self.get_version_pages(version.version_id)],
            }
            return canonical_sha256(content)

    def validate_decision(self, decision: ManualDecision) -> None:
        current = self.precondition_hash(decision.target_type, decision.target_id)
        if current != decision.precondition_hash:
            raise DecisionPreconditionConflict(decision.target_id, 'evidence_changed')

    def register_decision(self, decision: ManualDecision) -> WriteOutcome:
        with self.transaction():
            self.validate_decision(decision)
            old = self.get_decision(decision.decision_id)
            if old is not None:
                if replace(decision, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting manual decision')
                return WriteOutcome.IDENTICAL
            self._insert('manual_decisions', _COLUMNS, tuple(getattr(decision, name) for name in ManualDecision.__dataclass_fields__))
            return WriteOutcome.CREATED

    def get_decision(self, identity: str) -> ManualDecision | None:
        row = self._connection.execute('SELECT ' + _COLUMNS + ' FROM manual_decisions WHERE decision_id=?', (identity,)).fetchone()
        return ManualDecision(*row) if row is not None else None

    def list_decisions(self) -> tuple[ManualDecision, ...]:
        return tuple(ManualDecision(*row) for row in self._connection.execute(
            'SELECT ' + _COLUMNS + ' FROM manual_decisions ORDER BY decision_id'))

    def export_decisions(self) -> bytes:
        # Export even obsolete decisions: losing human history is worse than a
        # blocked replay. Validation is obligatory when importing/applying.
        with self.transaction():
            return encode_decisions(self.list_decisions())
