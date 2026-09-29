# Canonical SQLite connection and migrations

Infrastructure only. This package does not import `Nomina`, historical
`DatabaseService`, parsers, UI or domain repositories. There is no default
database path, no economic table and no automatic ingestion.

## Opening

```python
from src.persistence import open_database

# Explicit initialization; creates directories/file only in this mode.
with open_database(path, mode="create", application_revision="release-or-build-id") as db:
    assert db.status.current_version == 3

# Existing file only; applies pending known migrations.
with open_database(path, mode="migrate", application_revision="release-or-build-id") as db:
    status = db.status

# Default: existing file, SQLite URI mode=ro, query_only=ON, no migration.
with open_database(path) as db:
    pending = db.status.pending_versions
```

`DatabaseSession.connection` is an infrastructure handle for subsequent adapters,
not a domain contract. A session always closes its connection. Verification holds
a read snapshot until exit. Connections do not implicitly commit caller work;
unfinished explicit transactions are rolled back. `:memory:` requires `create`.

`connect` is the lower-level connection-only API with `create`, `read_write` and
`read_only` modes; it does not verify a schema. Missing paths are rejected in both
noncreating modes. Paths are resolved to escaped file URIs, so `#`, `?`, spaces and
Unicode in filenames are not interpreted as URI parameters. Raw URI input is
rejected. Relative paths are relative to the caller; use absolute paths when the
database location must be independent of cwd. SQL resources never depend on cwd.

## Connection policy

Every connection explicitly sets and verifies:

- `foreign_keys=ON`;
- `busy_timeout=5000` ms by default (injectable positive integer);
- `synchronous=FULL`;
- `query_only=ON` for read-only connections.

Writable disk connections use `journal_mode=DELETE`; memory uses `MEMORY`.
An existing different writable mode (including WAL) is rejected, not silently
converted. Read-only verification does not change the stored journal mode.
WAL, checkpoint management and concurrent writers are not introduced here.
There is no row factory or dependency on team/global SQLite settings.

Python autocommit is explicitly enabled. The runner owns SQL `BEGIN IMMEDIATE`,
`COMMIT` and `ROLLBACK`; it does not rely on sqlite3's implicit transaction defaults.

## Catalog and bootstrap

`sql/0001_schema_migrations.sql` creates the control ledger:

```text
schema_migrations(version PK, checksum, applied_at, application_revision)
```

The file's exact UTF-8 bytes (including line endings) define its SHA256. Resources
are loaded using `importlib.resources`. Catalog versions are positive, unique,
contiguous integers from 1 and sorted numerically, independent of file enumeration.
Injected `Migration` catalogs allow isolated tests and future versions.

A database with no user schema objects is version 0. Migration 1 creates the
control table and inserts its own record **in the same transaction**. There is no
separate bootstrap write. An existing control table without its initial record,
or a nonempty database without the table, is an error. Historical SQLite files
are never adopted or migrated automatically.

Each migration is a separate transaction, including its record and post-checks.
If version 2 fails after version 1 committed, version 1 remains, version 2 is absent,
and a later run can resume. A failed first migration may leave an empty file and
created directories, but no partial schema or migration record. They are not deleted.

SQL is executed statement by statement using `sqlite3.complete_statement` for
boundaries, preserving quoted semicolons, comments and trigger bodies. The runner
does not use `executescript`, which can interfere with transaction ownership.
An authorizer rejects transaction control, savepoints, ATTACH/DETACH, PRAGMAs,
temporary-schema work and mutation of the runner-owned ledger. VACUUM cannot run
inside the transaction. Nontransactional migrations are unsupported; no unsafe
fallback is attempted. Migrations are trusted application resources, not a SQL sandbox.

Before each migration the history is rechecked under the writer lock. Applied
versions are never rerun. Identical reopens do not change timestamps or records.
The UTC timestamp is generated at application; `application_revision` is injected,
defaults to `development`, and never invokes Git.

## Verification and errors

`verify_schema` checks FK activation, control-table columns, contiguous history,
known versions, exact checksums and audit metadata, then runs `integrity_check`
and `foreign_key_check`. Pending versions are returned, not applied in verification.
An empty existing file returns version 0/pending 1, 2 and 3 without bootstrap or writes.

Specific errors distinguish configuration, invalid definitions/history, unknown
future versions, checksum changes, execution failures and integrity failures.
SQLite exceptions arising inside these operations retain their cause and context.
Errors from a caller's own SQL remain the caller's responsibility.

**Engine limit:** SQLite 3.50.4 does not retain CHECK expressions when loading a
natively read-only database. Its read-only `integrity_check` therefore does not
evaluate those constraints, although FK and history checks still run. Verification
does not claim a stronger guarantee than the engine provides. Post-migration checks
use the writable connection and evaluate CHECKs. A caller needing that additional
check on an existing database can call `verify_schema` within `connect(...,
mode="read_write")`, without executing writes or migrations. Tests cover this
distinction rather than replacing read-only access with an implicit writable open.
See SQLite's [schema loading implementation](https://github.com/sqlite/sqlite/blob/version-3.50.4/src/build.c#L1799-L1827).

No backups, downgrades, schema repair, legacy adoption or economic migrations are
implemented. Subsequent migrations must preserve the migration-ledger contract.


## Identity and physical evidence (schema 2)

`sql/0002_identity_and_evidence.sql` adds exactly `persons`, `employers`,
`corpora`, `source_files`, `file_locations`, `ingest_runs`, and `ingest_items`.
It adds no document interpretation or economic tables. All foreign keys use
RESTRICT for both deletion and updates; child lookup indexes accompany them.
Version 1 bytes and checksums remain unchanged. Old infrastructure tests explicitly
inject the v1 catalog; identity/evidence tests inject v2. Document tests exercise
the current packaged catalog and the upgrade from v2.

Pure frozen records and ID constructors live in `src.canonical.evidence`.
`src.persistence.evidence.EvidenceRepository` takes the infrastructure connection
but its operations accept/return those records (or `None`), never rows/cursors.
Registration returns `WriteOutcome.CREATED` or `IDENTICAL`; divergent immutable
content raises `ReproducibilityConflict`. FK/CHECK violations remain SQLite
integrity errors at this adapter boundary. No persistence is coupled to `Nomina`.

Person/corpus IDs use a UUID seed (generated when omitted); callers retain the ID
or seed for subsequent registrations. Employer identity uses the supplied uppercase
country and exact, unpadded tax ID; no name matching, case folding or punctuation
removal guesses legal equivalence. Without tax ID an employer uses a UUID seed.
A file ID depends solely on its lowercase SHA256. Copies share a file and may have
multiple locations. Different files can occupy the same relative path. Paths are
normalized relative POSIX paths; original filenames must be basenames.
No file bytes or real corpus are read by this adapter.

Timestamps are explicit UTC ISO 8601 strings with UTC defaults on new records.
Identical registrations ignore newly supplied operational timestamps and preserve
the first persisted value. Contradictory metadata, including availability, is not
silently updated. Future availability decisions are outside this increment.

Ingestion plans have contract version 1 and use the existing canonical serialization
version 1. Plans accept null, booleans, integers, text, lists and string-keyed maps;
floats and economic typed values are outside this plan contract. JSON envelope,
type tags, canonical spelling/order, SHA256 and run identity are all validated.
`IngestRun.from_plan` builds them without exposing SQL. A plan hash identifies one
inventory run, not every process attempt; retries/attempt orchestration is deferred.

`register_item` records inventory. `update_item` explicitly updates a pending item
while its run is running; immutable identity fields cannot change. Terminal items
cannot be overwritten, but repeating identical updates is allowed. Processed items
require a physical file; when an expected hash exists it must match the linked file.
Skipped/failed items require a machine reason code. All free-form error detail is
replaced with `Details omitted; see reason_code.`: redacting only paths would not
reliably remove personal data. No raw exception or traceback is persisted.
`finish_run` records complete/partial with a UTC completion time. Complete cannot
contain pending/failed items; terminal runs cannot gain items or change status.
A repeated same-status finish preserves its original timestamp.

Every write uses a savepoint; `repository.transaction()` groups writes atomically,
including rollback on conflicts. Nested units compose with caller-owned transactions.
Inventory does not execute parsers or ingest a real corpus. It does not resolve
versions, interpret ALTEN or calculate KPIs.


## Documents and extractions (schema 3)

`sql/0003_documents_and_extractions.sql` adds only `logical_documents`,
`document_versions`, `version_pages` and `extractions`. Earlier migration bytes
remain unchanged. The same FK RESTRICT and immutable-registration policies apply.

Pure frozen records and helpers are in `src.canonical.documents`; the existing
`EvidenceRepository` registers/queries them and reuses its transactional writes.
No new connection, hashing or serialization infrastructure is introduced.

- `document_id(corpus_id, origin_key)` identifies a source-established logical unit.
  Origin keys are nonempty, stable, opaque keys within their corpus, not inferred
  from employer/month, filename or economic values. Type and optional employer
  are metadata; incompatible repetitions conflict rather than silently updating.
- `version_id(document_id, file_id, segment_key)` identifies a logical unit's
  physical source and scope. The segment key is supplied explicitly, even for a
  whole-file scope. One PDF can back different documents and segments. No version
  is selected as active, latest or preferred.
- `VersionPage` associates known one-based physical pages with nonnegative order
  positions. `(version_id, ordinal)` is the primary key; `(version_id, page_number)`
  is unique. Retrieval orders by ordinal, not page number. Missing page evidence
  is represented by no association, never a fabricated page 1. Ordinal gaps are
  allowed; absence of rows does not claim an empty PDF. Known `page_count` bounds
  are checked by the repository; unknown counts do not fabricate bounds. The same
  physical page may support multiple versions.
- `extraction_id(version_id, extractor_name, extractor_revision, config_hash)`
  identifies a reproducible extraction invocation. `content_hash` is its asserted
  output digest, deliberately outside identity: a different output under the same
  inputs raises `ReproducibilityConflict`. No output payload or facts are stored.

ID helpers normalize referenced canonical IDs to their string representation before
hashing, so typed IDs and strings read back from storage give identical identities.
All three timestamped registrations retain the first `created_at` on repetition.
Page associations also reject incompatible reuse of an ordinal or physical page.
Group chain registration in `repository.transaction()` for all-or-nothing writes.
Methods return frozen contracts, ordered tuples, or write outcomes, never SQL rows.
This increment neither imports corpus documents nor adapts `Nomina`.
