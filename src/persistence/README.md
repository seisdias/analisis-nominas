# Canonical SQLite connection and migrations

Infrastructure only. This package does not import `Nomina`, historical
`DatabaseService`, parsers, UI or domain repositories. There is no default
database path, no economic table and no automatic ingestion.

## Opening

```python
from src.persistence import open_database

# Explicit initialization; creates directories/file only in this mode.
with open_database(path, mode="create", application_revision="release-or-build-id") as db:
    assert db.status.current_version == 1

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

`sql/0001_schema_migrations.sql` is the only packaged migration. It creates only:

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
An empty existing file returns version 0/pending 1 without bootstrap or writes.

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
