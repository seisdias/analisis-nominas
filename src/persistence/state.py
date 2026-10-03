"""Read-only logical state comparison for the complete canonical v7 dataset.

Text is retained verbatim, including canonical JSON and original documentary
payloads. No semantic equivalence of different strings, filenames, JSON spellings
or relative paths is invented. Rows/columns/tables have deterministic ordering;
SQLite physical pages, rowids, indexes and file location are not state inputs.
"""

from dataclasses import dataclass

from src.canonical.serialization import canonical_bytes, sha256_bytes
from src.persistence.evidence import EvidenceRepository
from src.persistence.migrations import verify_schema

# Explicit exclusions, not a suffix/name heuristic. Human decision audit dates
# and schema application_revision remain included. All other columns are included.
OPERATIONAL_COLUMNS: dict[str, frozenset[str]] = {
    'schema_migrations': frozenset({'applied_at'}),
    'persons': frozenset({'created_at'}),
    'employers': frozenset({'created_at'}),
    'corpora': frozenset({'created_at'}),
    'source_files': frozenset({'created_at'}),
    'file_locations': frozenset({'first_seen_at'}),
    'ingest_runs': frozenset({'started_at', 'finished_at'}),
    'ingest_items': frozenset(),
    'logical_documents': frozenset({'created_at'}),
    'document_versions': frozenset({'created_at'}),
    'version_pages': frozenset(),
    'extractions': frozenset({'created_at'}),
    'documentary_facts': frozenset({'created_at'}),
    'fact_pages': frozenset(),
    'rules': frozenset({'created_at'}),
    'assessments': frozenset({'created_at'}),
    'economic_observations': frozenset({'created_at'}),
    'observation_facts': frozenset(),
    'document_relations': frozenset({'created_at'}),
    'observation_relations': frozenset({'created_at'}),
    'manual_decisions': frozenset(),
}


class StateContractError(ValueError):
    """Cannot represent this database using the complete v7 comparison contract."""


@dataclass(frozen=True, slots=True)
class CanonicalState:
    canonical_content: bytes
    table_counts: tuple[tuple[str, int], ...]

    @property
    def fingerprint(self) -> str:
        return sha256_bytes(self.canonical_content)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class CanonicalStateReader(EvidenceRepository):
    """Returns immutable canonical bytes/counts, never cursors or SQLite rows.

    One read snapshot covers integrity verification and all rows. Logical mode
    excludes only OPERATIONAL_COLUMNS; strict mode includes every stored column
    and is intended to detect *any* persisted change on identical-plan replay.
    No mutation, schema initialization, migration or economic calculation occurs.
    """

    def read(self, *, include_operational_metadata: bool = False) -> CanonicalState:
        with self.transaction():
            status = verify_schema(self._connection)
            if status.current_version != 7 or status.pending_versions:
                raise StateContractError('Logical state contract requires canonical schema v7')
            tables = {r[0] for r in self._connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables != set(OPERATIONAL_COLUMNS):
                raise StateContractError('Unexpected or missing canonical table; comparison would be incomplete')
            state = {}
            counts = []
            for table in sorted(tables):
                available = {r[1] for r in self._connection.execute(f'PRAGMA table_info({_quote(table)})')}
                if not OPERATIONAL_COLUMNS[table] <= available:
                    raise StateContractError('Missing expected operational columns')
                columns = sorted(available if include_operational_metadata else available - OPERATIONAL_COLUMNS[table])
                rows = [list(row) for row in self._connection.execute(
                    f'SELECT {", ".join(_quote(c) for c in columns)} FROM {_quote(table)}')]
                try:
                    rows.sort(key=canonical_bytes)
                except TypeError as error:
                    raise StateContractError('Unsupported persisted value (float/blob)') from error
                state[table] = {'columns': columns, 'rows': rows}
                counts.append((table, len(rows)))
            encoded = canonical_bytes({
                'contract': 'canonical-persisted-state/v1', 'schema_version': 7,
                'mode': 'strict' if include_operational_metadata else 'logical', 'tables': state,
            })
            return CanonicalState(encoded, tuple(counts))
