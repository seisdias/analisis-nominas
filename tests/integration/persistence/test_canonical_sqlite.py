"""Canonical infrastructure against isolated SQLite, never the payroll corpus."""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest

from src.persistence import (
    ConnectionConfigurationError,
    InvalidMigrationError,
    Migration,
    MigrationChecksumError,
    MigrationExecutionError,
    SchemaIntegrityError,
    UnknownSchemaVersionError,
    connect,
    verify_schema,
)
from src.persistence import (
    load_migrations as packaged_migrations,
)
from src.persistence import (
    open_database as packaged_open_database,
)


# These infrastructure scenarios exercise the original v1 bootstrap, with
# synthetic later migrations. Real packaged v2 is covered in test_evidence.py.
def load_migrations() -> tuple[Migration, ...]:
    return packaged_migrations()[:1]


def open_database(
    path: str | Path, *, mode: Literal["create", "migrate", "verify"] = "verify", **kwargs: Any,
):
    kwargs.setdefault("migrations", load_migrations())
    return packaged_open_database(path, mode=mode, **kwargs)


def catalog(*sql: str) -> tuple[Migration, ...]:
    return (*load_migrations(), *(Migration(i, text) for i, text in enumerate(sql, 2)))


def tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


@pytest.mark.parametrize("memory", [False, True])
def test_configured_connection_and_close(tmp_path: Path, memory: bool) -> None:
    path = ":memory:" if memory else str(tmp_path / "nested" / "canonical.sqlite")
    with connect(path, mode="create") as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert conn.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert conn.execute("PRAGMA synchronous").fetchone() == (2,)
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("memory" if memory else "delete",)
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child VALUES (123)")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


@pytest.mark.parametrize("mode", ["read_only", "read_write"])
def test_noncreating_modes_never_create_directories(tmp_path: Path, mode: Any) -> None:
    path = tmp_path / "missing" / "db.sqlite"
    with pytest.raises(ConnectionConfigurationError):
        with connect(path, mode=mode):
            pytest.fail("Missing file must not open")
    assert not path.parent.exists()


@pytest.mark.parametrize("mode", ["verify", "migrate"])
def test_high_level_noncreating_modes(tmp_path: Path, mode: Any) -> None:
    path = tmp_path / "missing" / "db.sqlite"
    with pytest.raises(ConnectionConfigurationError):
        with open_database(path, mode=mode):
            pytest.fail("Missing file must not open")
    assert not path.parent.exists()


@pytest.mark.parametrize("timeout", [0, -1, True, 1.5, 2**31])
def test_invalid_timeout_is_explicit(timeout: Any) -> None:
    with pytest.raises(ConnectionConfigurationError):
        with connect(":memory:", mode="create", busy_timeout_ms=timeout):
            pytest.fail("Invalid timeout accepted")


def test_invalid_modes_and_paths(tmp_path: Path) -> None:
    for path, mode in [("", "create"), ("file:surprise?mode=rwc", "create"),
                       (":memory:", "read_only"), (str(tmp_path), "create"),
                       (str(tmp_path / "x"), "invalid")]:
        with pytest.raises(ConnectionConfigurationError):
            with connect(path, mode=mode):  # type: ignore[arg-type]
                pytest.fail("Invalid connection accepted")
    with pytest.raises(ConnectionConfigurationError):
        with open_database(tmp_path / "missing", mode="invalid"):  # type: ignore[arg-type]
            pytest.fail("Invalid mode accepted")


def test_connection_rolls_back_unfinished_transaction_on_exception(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with pytest.raises(RuntimeError, match="caller"):
        with connect(path, mode="create") as conn:
            conn.execute("BEGIN")
            conn.execute("CREATE TABLE unfinished(id INTEGER)")
            raise RuntimeError("caller")
    with connect(path, mode="read_only") as fresh:
        assert "unfinished" not in tables(fresh)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_configuration_is_checked_and_failed_connection_is_closed() -> None:
    class IgnoredForeignKeys(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA foreign_keys = ON":
                return super().execute("SELECT 1")
            return super().execute(sql, *args, **kwargs)

    conn = sqlite3.connect(":memory:", factory=IgnoredForeignKeys)
    with patch("src.persistence.connection.sqlite3.connect", return_value=conn):
        with pytest.raises(ConnectionConfigurationError, match="foreign_keys"):
            with connect(":memory:", mode="create"):
                pytest.fail("Unchecked foreign_keys")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_reopening_reapplies_configuration(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with connect(path, mode="create") as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA busy_timeout = 1")
    with connect(path, mode="read_write", busy_timeout_ms=37) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert conn.execute("PRAGMA synchronous").fetchone() == (2,)
        assert conn.execute("PRAGMA busy_timeout").fetchone() == (37,)


def test_resources_and_absolute_path_are_independent_of_cwd(tmp_path: Path, monkeypatch) -> None:
    expected = load_migrations()
    monkeypatch.chdir(tmp_path)
    assert load_migrations() == expected
    path = tmp_path / "other #? ñ" / "db.sqlite"
    with open_database(path, mode="create") as db:
        assert db.status.current_version == 1
    with open_database(path) as db:
        assert db.status.pending_versions == ()


@pytest.mark.parametrize("memory", [False, True])
def test_bootstrap_only_control_table_and_revision(tmp_path: Path, memory: bool) -> None:
    path = ":memory:" if memory else str(tmp_path / "db.sqlite")
    with open_database(path, mode="create", application_revision="release-test") as db:
        assert tables(db.connection) == {"schema_migrations"}
        assert db.status.current_version == db.status.latest_version == 1
        assert db.status.pending_versions == ()
        row = db.connection.execute("SELECT * FROM schema_migrations").fetchone()
        assert row[0] == 1
        assert row[1] == hashlib.sha256(load_migrations()[0].sql.encode("utf-8")).hexdigest()
        offset = datetime.fromisoformat(row[2]).utcoffset()
        assert offset is not None and offset.total_seconds() == 0
        assert row[3] == "release-test"
    with pytest.raises(sqlite3.ProgrammingError):
        db.connection.execute("SELECT 1")


@pytest.mark.parametrize(("version", "checksum", "revision"), [
    (0, "a" * 64, "test"), (-1, "a" * 64, "test"),
    (2, "x" * 64, "test"), (2, "A" * 64, "test"), (2, "a" * 63, "test"),
    (2, "a" * 64, ""), (2, None, "test"),
])
def test_control_table_constraints(version: int, checksum: str | None, revision: str) -> None:
    with open_database(":memory:", mode="create") as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                                  (version, checksum, "2026-01-01T00:00:00+00:00", revision))


def test_applies_in_version_order_and_only_pending(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    migrations = catalog("CREATE TABLE sample(value TEXT); INSERT INTO sample VALUES ('one');",
                         "INSERT INTO sample VALUES ('two');")
    with open_database(path, mode="create", migrations=migrations[:2]):
        pass
    with open_database(path, mode="migrate", migrations=tuple(reversed(migrations))) as db:
        assert db.status.current_version == 3
        assert db.connection.execute("SELECT value FROM sample").fetchall() == [("one",), ("two",)]
        before = db.connection.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall()
    with open_database(path, mode="migrate", migrations=migrations) as db:
        assert db.connection.execute("SELECT value FROM sample").fetchall() == [("one",), ("two",)]
        assert db.connection.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall() == before


def test_verify_detects_pending_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create"):
        pass
    before = path.read_bytes()
    with open_database(path, migrations=catalog("CREATE TABLE later(id INTEGER);")) as db:
        assert db.status.current_version == 1
        assert db.status.latest_version == 2
        assert db.status.pending_versions == (2,)
        assert tables(db.connection) == {"schema_migrations"}
        assert db.connection.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            db.connection.execute("CREATE TABLE forbidden(id INTEGER)")
    assert path.read_bytes() == before


def test_verify_empty_file_is_version_zero_without_bootstrap(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    path.touch()
    with open_database(path) as db:
        assert db.status.current_version == 0
        assert db.status.pending_versions == (1,)
        assert tables(db.connection) == set()
    assert path.read_bytes() == b""


@pytest.mark.parametrize("mode", ["verify", "migrate"])
def test_applied_checksum_mismatch_is_rejected(tmp_path: Path, mode: Any) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create"):
        pass
    original = load_migrations()[0]
    altered = (Migration(1, original.sql + "\n-- changed bytes\n"),)
    with pytest.raises(MigrationChecksumError):
        with open_database(path, mode=mode, migrations=altered):
            pytest.fail("Changed migration accepted")


@pytest.mark.parametrize("mode", ["verify", "migrate"])
def test_unknown_future_schema_is_rejected(tmp_path: Path, mode: Any) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create", migrations=catalog("CREATE TABLE future(id INTEGER);")):
        pass
    with pytest.raises(UnknownSchemaVersionError):
        with open_database(path, mode=mode):
            pytest.fail("Future schema accepted")


def test_stored_checksum_tampering_is_rejected_without_repair(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create") as db:
        db.connection.execute("UPDATE schema_migrations SET checksum=?", ("0" * 64,))
    before = path.read_bytes()
    with pytest.raises(MigrationChecksumError):
        with open_database(path):
            pytest.fail("Tampered checksum accepted")
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", [
    "DELETE FROM schema_migrations WHERE version=1",
    "DELETE FROM schema_migrations",
    "UPDATE schema_migrations SET applied_at='not-a-time' WHERE version=1",
])
def test_corrupt_history_is_rejected(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "db.sqlite"
    migrations = catalog("CREATE TABLE sample(id INTEGER);")
    with open_database(path, mode="create", migrations=migrations) as db:
        db.connection.execute(damage)
    with pytest.raises(InvalidMigrationError):
        with open_database(path, migrations=migrations):
            pytest.fail("Corrupt history accepted")


@pytest.mark.parametrize("sql", [
    "CREATE TABLE documentos(id TEXT)",
    "CREATE TABLE schema_migrations(version INTEGER)",
    "CREATE VIEW schema_migrations AS SELECT 1 AS version",
])
def test_unmanaged_or_malformed_schema_is_not_adopted(tmp_path: Path, sql: str) -> None:
    path = tmp_path / "unmanaged.sqlite"
    with connect(path, mode="create") as conn:
        conn.execute(sql)
    before = path.read_bytes()
    with pytest.raises(InvalidMigrationError):
        with open_database(path, mode="migrate"):
            pytest.fail("Unmanaged schema adopted")
    assert path.read_bytes() == before


@pytest.mark.parametrize("versions", [[], [1, 1], [2], [1, 3]])
def test_invalid_migration_catalog_fails_before_creating_file(tmp_path: Path, versions) -> None:
    path = tmp_path / "not-created" / "db.sqlite"
    migrations = tuple(Migration(v, "SELECT 1;") for v in versions)
    with pytest.raises(InvalidMigrationError):
        with open_database(path, mode="create", migrations=migrations):
            pytest.fail("Invalid catalog accepted")
    assert not path.parent.exists()


@pytest.mark.parametrize(("version", "sql"), [(0, "SELECT 1;"), (True, "SELECT 1;"),
                                            (1, ""), (1, "  "), (1, 23)])
def test_invalid_migration_definition(version: Any, sql: Any) -> None:
    with pytest.raises(InvalidMigrationError):
        Migration(version, sql)


def test_failed_migration_rolls_back_ddl_and_data(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    migrations = catalog("CREATE TABLE partial(value TEXT); INSERT INTO partial VALUES ('x');"
                         "INSERT INTO nonexistent VALUES (1);")
    with pytest.raises(MigrationExecutionError, match="2"):
        with open_database(path, mode="create", migrations=migrations):
            pytest.fail("Failed migration accepted")
    with open_database(path, migrations=migrations) as db:
        assert db.status.current_version == 1
        assert db.status.pending_versions == (2,)
        assert tables(db.connection) == {"schema_migrations"}


def test_failed_first_migration_rolls_back_bootstrap(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    first = Migration(1, load_migrations()[0].sql + "\nINSERT INTO missing VALUES (1);")
    with pytest.raises(MigrationExecutionError):
        with open_database(path, mode="create", migrations=(first,)):
            pytest.fail("Failed bootstrap accepted")
    with connect(path, mode="read_only") as conn:
        assert tables(conn) == set()


def test_record_failure_rolls_back_migration_too(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create") as db:
        db.connection.execute("""CREATE TRIGGER reject_record BEFORE INSERT ON schema_migrations
            WHEN NEW.version=2 BEGIN SELECT RAISE(ABORT, 'synthetic record failure'); END""")
    with pytest.raises(MigrationExecutionError):
        with open_database(path, mode="migrate", migrations=catalog("CREATE TABLE partial(x);")):
            pytest.fail("Failed record accepted")
    with open_database(path) as db:
        assert tables(db.connection) == {"schema_migrations"}
        assert db.status.current_version == 1


def test_commit_failure_rolls_back_schema_and_record(tmp_path: Path) -> None:
    class FailedCommit(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "COMMIT":
                raise sqlite3.OperationalError("synthetic commit failure")
            return super().execute(sql, *args, **kwargs)

    path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(path, factory=FailedCommit, autocommit=True)
    with patch("src.persistence.connection.sqlite3.connect", return_value=conn):
        with pytest.raises(MigrationExecutionError, match="commit failure"):
            with open_database(path, mode="create"):
                pytest.fail("Failed commit accepted")
    with open_database(path) as db:
        assert db.status.current_version == 0
        assert tables(db.connection) == set()


@pytest.mark.parametrize("sql", [
    "COMMIT;", "ROLLBACK;", "BEGIN;", "SAVEPOINT escape;",
    "PRAGMA foreign_keys=OFF;", "PRAGMA user_version=77;",
    "ATTACH DATABASE ':memory:' AS extra;", "VACUUM;",
    "DELETE FROM schema_migrations;", "DROP TABLE schema_migrations;",
    "ALTER TABLE schema_migrations RENAME TO hidden;",
])
def test_migration_cannot_escape_atomicity_or_rewrite_ledger(tmp_path: Path, sql: str) -> None:
    path = tmp_path / "db.sqlite"
    migrations = catalog("CREATE TABLE partial(x); " + sql)
    with pytest.raises(MigrationExecutionError):
        with open_database(path, mode="create", migrations=migrations):
            pytest.fail("Unsafe SQL accepted")
    with open_database(path) as db:
        assert tables(db.connection) == {"schema_migrations"}


def test_sql_splitter_handles_strings_comments_and_triggers() -> None:
    sql = """-- a comment with ;
        CREATE TABLE sample(value TEXT);
        CREATE TABLE audit(value TEXT);
        CREATE TRIGGER sample_log AFTER INSERT ON sample BEGIN
            INSERT INTO audit VALUES ('semi;colon');
            INSERT INTO audit VALUES (NEW.value);
        END;
        INSERT INTO sample VALUES ('quote'';value'); -- trailing comment
    """
    with open_database(":memory:", mode="create", migrations=catalog(sql)) as db:
        assert db.connection.execute("SELECT value FROM audit").fetchall() == [
            ("semi;colon",), ("quote';value",),
        ]


def test_foreign_key_violation_is_detected_and_migration_rolls_back(tmp_path: Path) -> None:
    migrations = catalog("CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                         "CREATE TABLE child(id REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);"
                         "INSERT INTO child VALUES (1);")
    path = tmp_path / "db.sqlite"
    with pytest.raises(SchemaIntegrityError):
        with open_database(path, mode="create", migrations=migrations):
            pytest.fail("Broken FK accepted")
    with open_database(path) as db:
        assert tables(db.connection) == {"schema_migrations"}


@pytest.mark.parametrize("kind", ["foreign_key", "check"])
def test_reusable_integrity_verification_detects_corruption(tmp_path: Path, kind: str) -> None:
    migrations = catalog("CREATE TABLE parent(id INTEGER PRIMARY KEY);"
                         "CREATE TABLE child(id INTEGER REFERENCES parent(id), x INTEGER CHECK(x>0));")
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create", migrations=migrations):
        pass
    with sqlite3.connect(path) as raw:
        raw.execute("PRAGMA ignore_check_constraints=ON")
        raw.execute("INSERT INTO child VALUES (?, ?)", (1, 1) if kind == "foreign_key" else (None, -1))
    raw.close()
    # SQLite 3.50.4 omits CHECK expressions when loading a read-only database.
    # Use the same writable connection type used for post-migration checks.
    with connect(path, mode="read_write") as conn:
        with pytest.raises(SchemaIntegrityError):
            verify_schema(conn, migrations)
    if kind == "foreign_key":
        with pytest.raises(SchemaIntegrityError):
            with open_database(path, migrations=migrations):
                pytest.fail("Foreign-key corruption accepted in read-only mode")


def test_verify_requires_foreign_keys_on() -> None:
    with open_database(":memory:", mode="create") as db:
        db.connection.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(ConnectionConfigurationError):
            verify_schema(db.connection)


def test_non_database_error_has_context(tmp_path: Path) -> None:
    path = tmp_path / "not-sqlite"
    path.write_text("not a SQLite database")
    with pytest.raises(ConnectionConfigurationError):
        with open_database(path):
            pytest.fail("Invalid file accepted")


def test_locked_migration_fails_explicitly_without_partial_work(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    with open_database(path, mode="create"):
        pass
    with connect(path, mode="read_write") as lock:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(MigrationExecutionError):
            with open_database(path, mode="migrate", busy_timeout_ms=1):
                pytest.fail("Writer lock ignored")


@pytest.mark.parametrize("revision", ["", " ", None])
def test_invalid_application_revision_does_not_create_file(tmp_path: Path, revision: Any) -> None:
    path = tmp_path / "missing" / "db.sqlite"
    with pytest.raises(InvalidMigrationError):
        with open_database(path, mode="create", application_revision=revision):
            pytest.fail("Invalid revision accepted")
    assert not path.parent.exists()
