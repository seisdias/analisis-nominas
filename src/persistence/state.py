"""Read-only source-state comparison for v7/v8 and optional derived-cache audit.

Text is retained verbatim, including canonical JSON and original documentary
payloads. No semantic equivalence of different strings, filenames, JSON spellings
or relative paths is invented. Rows/columns/tables have deterministic ordering;
SQLite physical pages, rowids, indexes and file location are not state inputs.
"""

from dataclasses import dataclass

from src.canonical.serialization import canonical_bytes, sha256_bytes
from src.persistence.evidence import EvidenceRepository
from src.persistence.migrations import load_migrations, verify_schema

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
    """Cannot represent this database using a supported complete comparison contract."""


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
    and detects operational changes too. On v8, include_derived_cache=True is
    additionally required to audit cache rows; dataset revision always excludes
    them. v7 retains the byte-for-byte v1 representation from T6.12.
    No mutation, schema initialization, migration or economic calculation occurs.
    """

    def read(self, *, include_operational_metadata: bool = False,
             include_derived_cache: bool = False) -> CanonicalState:
        with self.transaction():
            version = self._connection.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]
            if version not in (7, 8):
                raise StateContractError('Logical state contract requires canonical schema v7 or v8')
            verify_schema(self._connection, load_migrations()[:version])
            cache_columns = {'derived_results': frozenset({'created_at'}), 'derived_inputs': frozenset()}
            expected = dict(OPERATIONAL_COLUMNS)
            if version == 8:
                expected.update(cache_columns)
            tables = {r[0] for r in self._connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables != set(expected):
                raise StateContractError('Unexpected or missing canonical table; comparison would be incomplete')
            state = {}
            counts = []
            selected = tables if include_derived_cache else tables - set(cache_columns)
            for table in sorted(selected):
                available = {r[1] for r in self._connection.execute(f'PRAGMA table_info({_quote(table)})')}
                if not expected[table] <= available:
                    raise StateContractError('Missing expected operational columns')
                columns = sorted(available if include_operational_metadata else available - expected[table])
                rows = [list(row) for row in self._connection.execute(
                    f'SELECT {", ".join(_quote(c) for c in columns)} FROM {_quote(table)}')]
                try:
                    rows.sort(key=canonical_bytes)
                except TypeError as error:
                    raise StateContractError('Unsupported persisted value (float/blob)') from error
                state[table] = {'columns': columns, 'rows': rows}
                counts.append((table, len(rows)))
            envelope = {
                'contract': 'canonical-persisted-state/v1' if version == 7 else 'canonical-persisted-state/v2',
                'schema_version': version,
                'mode': 'strict' if include_operational_metadata else 'logical', 'tables': state,
            }
            if version == 8:
                envelope['scope'] = 'global-with-cache' if include_derived_cache else 'source'
            encoded = canonical_bytes(envelope)
            return CanonicalState(encoded, tuple(counts))
