"""Canonical SQLite infrastructure; separate from pure canonical contracts."""

from src.persistence.connection import connect
from src.persistence.errors import (
    CanonicalSQLiteError,
    ConnectionConfigurationError,
    InvalidMigrationError,
    MigrationChecksumError,
    MigrationExecutionError,
    SchemaIntegrityError,
    UnknownSchemaVersionError,
)
from src.persistence.migrations import (
    DatabaseSession,
    Migration,
    SchemaStatus,
    load_migrations,
    open_database,
    verify_schema,
)

__all__ = [
    "CanonicalSQLiteError", "ConnectionConfigurationError", "DatabaseSession",
    "InvalidMigrationError", "Migration", "MigrationChecksumError", "MigrationExecutionError",
    "SchemaIntegrityError", "SchemaStatus", "UnknownSchemaVersionError", "connect",
    "load_migrations", "open_database", "verify_schema",
]
