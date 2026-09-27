"""Package SQL, immutable checksums and per-version atomic migration control."""

import hashlib
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Literal

from src.persistence.connection import ConnectionMode, connect
from src.persistence.errors import (
    ConnectionConfigurationError,
    InvalidMigrationError,
    MigrationChecksumError,
    MigrationExecutionError,
    SchemaIntegrityError,
    UnknownSchemaVersionError,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    sql: str

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version <= 0:
            raise InvalidMigrationError("Migration version must be a positive integer")
        if type(self.sql) is not str or not self.sql.strip():
            raise InvalidMigrationError("Migration SQL must be nonempty text")
        try:
            self.sql.encode("utf-8")
        except UnicodeError as error:
            raise InvalidMigrationError("Migration SQL must be valid UTF-8") from error

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    current_version: int
    latest_version: int
    pending_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DatabaseSession:
    """Infrastructure handle only; never a domain/repository return contract."""

    connection: sqlite3.Connection
    status: SchemaStatus


def _catalog(migrations: Sequence[Migration]) -> tuple[Migration, ...]:
    if not migrations or any(type(m) is not Migration for m in migrations):
        raise InvalidMigrationError("A nonempty migration catalog is required")
    ordered = tuple(sorted(migrations, key=lambda m: m.version))
    if tuple(m.version for m in ordered) != tuple(range(1, len(ordered) + 1)):
        raise InvalidMigrationError("Migration versions must be unique and contiguous from 1")
    return ordered


def load_migrations() -> tuple[Migration, ...]:
    """Read exact UTF-8 bytes, including line endings, independently of cwd."""
    result = []
    try:
        for resource in files("src.persistence").joinpath("sql").iterdir():
            if not resource.name.endswith(".sql"):
                continue
            match = re.fullmatch(r"([0-9]+)_[a-z0-9_]+\.sql", resource.name)
            if match is None:
                raise InvalidMigrationError(f"Invalid migration filename: {resource.name}")
            result.append(Migration(int(match[1]), resource.read_bytes().decode("utf-8")))
    except (OSError, UnicodeError) as error:
        raise InvalidMigrationError("Cannot read packaged SQL migrations") from error
    return _catalog(result)


def _history(conn: sqlite3.Connection, catalog: tuple[Migration, ...]) -> SchemaStatus:
    objects = dict(conn.execute(
        "SELECT name, type FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
    ))
    if "schema_migrations" not in objects:
        if objects:
            raise InvalidMigrationError("Nonempty unmanaged database; historical schemas are not adopted")
        return SchemaStatus(0, len(catalog), tuple(m.version for m in catalog))
    if objects["schema_migrations"] != "table":
        raise InvalidMigrationError("schema_migrations must be a table")
    columns = [(row[1], row[2], row[3], row[5])
               for row in conn.execute("PRAGMA table_info(schema_migrations)")]
    if columns != [("version", "INTEGER", 1, 1), ("checksum", "TEXT", 1, 0),
                   ("applied_at", "TEXT", 1, 0), ("application_revision", "TEXT", 1, 0)]:
        raise InvalidMigrationError("Invalid schema_migrations columns")
    rows = conn.execute("SELECT version, checksum, applied_at, application_revision "
                        "FROM schema_migrations ORDER BY version").fetchall()
    if not rows:
        raise InvalidMigrationError("Control table exists without its bootstrap migration record")
    if any(type(row[0]) is not int or row[0] <= 0 for row in rows):
        raise InvalidMigrationError("Invalid stored migration version")
    if rows[-1][0] > len(catalog):
        raise UnknownSchemaVersionError(f"Unknown schema version {rows[-1][0]}")
    if [row[0] for row in rows] != list(range(1, len(rows) + 1)):
        raise InvalidMigrationError("Migration history has gaps")
    for version, checksum, applied_at, revision in rows:
        if checksum != catalog[version - 1].checksum:
            raise MigrationChecksumError(f"Checksum mismatch for migration {version}")
        try:
            timestamp = datetime.fromisoformat(applied_at)
        except (TypeError, ValueError) as error:
            raise InvalidMigrationError(f"Invalid timestamp for migration {version}") from error
        if timestamp.utcoffset() != timedelta(0) or not isinstance(revision, str) or not revision.strip():
            raise InvalidMigrationError(f"Invalid audit metadata for migration {version}")
    current = rows[-1][0]
    return SchemaStatus(current, len(catalog), tuple(m.version for m in catalog if m.version > current))


def verify_schema(
    conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None,
) -> SchemaStatus:
    """Read-only checks; caller owns connection/snapshot. Pending is not corruption."""
    catalog = load_migrations() if migrations is None else _catalog(migrations)
    try:
        if conn.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise ConnectionConfigurationError("Schema verification requires foreign_keys=ON")
        status = _history(conn, catalog)
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise SchemaIntegrityError(f"SQLite integrity_check failed: {integrity}")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise SchemaIntegrityError("SQLite foreign_key_check found violations")
        return status
    except sqlite3.Error as error:
        raise SchemaIntegrityError(f"Cannot verify canonical SQLite: {error}") from error


def _statements(sql: str) -> Iterator[str]:
    buffer = []
    for char in sql:
        buffer.append(char)
        if char == ";" and sqlite3.complete_statement("".join(buffer)):
            yield "".join(buffer)
            buffer.clear()
    if "".join(buffer).strip():
        yield "".join(buffer)


def _authorize(action: int, first: str | None, second: str | None,
               database: str | None, trigger: str | None) -> int:
    # Guard atomicity, connection settings, and the runner-owned migration ledger.
    if action in (sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_ATTACH,
                  sqlite3.SQLITE_DETACH, sqlite3.SQLITE_PRAGMA) or database == "temp":
        return sqlite3.SQLITE_DENY
    ledger = "schema_migrations"
    if first == ledger and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                                      sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_TABLE):
        return sqlite3.SQLITE_DENY
    if second == ledger and action in (sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_CREATE_TRIGGER,
                                       sqlite3.SQLITE_DROP_TRIGGER):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _apply(conn: sqlite3.Connection, catalog: tuple[Migration, ...], revision: str) -> SchemaStatus:
    if conn.in_transaction:
        raise InvalidMigrationError("Migrations require a connection without an active transaction")
    while True:
        version: int | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Recheck under the writer lock, including after another process migrates.
            status = verify_schema(conn, catalog)
            if not status.pending_versions:
                conn.execute("COMMIT")
                return status
            version = status.pending_versions[0]
            migration = catalog[version - 1]
            conn.set_authorizer(_authorize)
            try:
                for statement in _statements(migration.sql):
                    conn.execute(statement)
            finally:
                conn.set_authorizer(None)
            conn.execute("INSERT INTO schema_migrations "
                         "(version, checksum, applied_at, application_revision) VALUES (?, ?, ?, ?)",
                         (version, migration.checksum, datetime.now(timezone.utc).isoformat(), revision))
            verify_schema(conn, catalog)
            conn.execute("COMMIT")
        except BaseException as error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise MigrationExecutionError(f"Migration {version or 'lock acquisition'} failed: {error}") from error
            raise


@contextmanager
def open_database(
    path: str | Path, *, mode: Literal["create", "migrate", "verify"] = "verify",
    application_revision: str = "development", migrations: Sequence[Migration] | None = None,
    busy_timeout_ms: int = 5000,
) -> Iterator[DatabaseSession]:
    """Verify by default; creating and migration are separate explicit operations.

    The packaged catalog defines the current schema. Injected catalogs support isolated
    versions and synthetic tests without modifying installed SQL resources.
    """
    if mode not in ("create", "migrate", "verify"):
        raise ConnectionConfigurationError(f"Unknown database mode: {mode}")
    catalog = load_migrations() if migrations is None else _catalog(migrations)
    if not isinstance(application_revision, str) or not application_revision.strip():
        raise InvalidMigrationError("application_revision must be explicit nonempty text")
    connection_mode: ConnectionMode = "read_only"
    if mode == "create":
        connection_mode = "create"
    elif mode == "migrate":
        connection_mode = "read_write"
    with connect(path, mode=connection_mode, busy_timeout_ms=busy_timeout_ms) as conn:
        if mode == "verify":
            conn.execute("BEGIN")
            status = verify_schema(conn, catalog)
            # Keep the read snapshot for the lifetime of the verification session.
        else:
            status = _apply(conn, catalog, application_revision)
        yield DatabaseSession(conn, status)
