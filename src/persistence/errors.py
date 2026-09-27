"""Errors owned by canonical SQLite infrastructure, not by economic domain."""


class CanonicalSQLiteError(RuntimeError):
    """Canonical storage could not be opened, verified or evolved safely."""


class ConnectionConfigurationError(CanonicalSQLiteError):
    """Opening or mandatory connection configuration failed."""


class InvalidMigrationError(CanonicalSQLiteError):
    """Invalid migration definitions, unmanaged schema or inconsistent history."""


class UnknownSchemaVersionError(InvalidMigrationError):
    """The database includes a version this application does not know."""


class MigrationChecksumError(InvalidMigrationError):
    """An applied migration does not match the supplied immutable SQL bytes."""


class MigrationExecutionError(CanonicalSQLiteError):
    """Migration transaction failed; its uncommitted effects were rolled back."""


class SchemaIntegrityError(CanonicalSQLiteError):
    """SQLite integrity_check or foreign_key_check found a violation."""
