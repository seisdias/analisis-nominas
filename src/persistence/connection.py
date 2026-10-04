"""Explicit connection lifetime and settings for canonical SQLite only."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from src.persistence.errors import ConnectionConfigurationError

type ConnectionMode = Literal["create", "read_write", "read_only"]


@contextmanager
def connect(
    path: str | Path, *, mode: ConnectionMode = "read_only", busy_timeout_ms: int = 5000,
) -> Iterator[sqlite3.Connection]:
    """Infrastructure-only connection; default never creates or writes a file.

    The context manages lifetime, not automatic commit. Unfinished explicit
    transactions are rolled back on exit. No canonical database path is implicit.
    """
    if mode not in ("create", "read_write", "read_only"):
        raise ConnectionConfigurationError(f"Unknown connection mode: {mode}")
    if type(busy_timeout_ms) is not int or not 0 < busy_timeout_ms < 2**31:
        raise ConnectionConfigurationError("busy_timeout_ms must be an integer in 1..2147483647")
    if not isinstance(path, (str, Path)) or not str(path) or str(path).startswith("file:"):
        raise ConnectionConfigurationError("An explicit filesystem path is required, not a URI")
    memory = str(path) == ":memory:"
    if memory and mode != "create":
        raise ConnectionConfigurationError(":memory: requires explicit create mode")
    conn: sqlite3.Connection | None = None
    try:
        if memory:
            location = ":memory:"
        else:
            target = Path(path).resolve()
            if mode == "create":
                target.parent.mkdir(parents=True, exist_ok=True)
            uri_mode = {"create": "rwc", "read_write": "rw", "read_only": "ro"}[mode]
            location = f"{target.as_uri()}?mode={uri_mode}"
        conn = sqlite3.connect(
            location, uri=not memory, timeout=busy_timeout_ms / 1000,
            isolation_level=None, autocommit=True,
            cached_statements=0,
        )
        conn.execute("PRAGMA foreign_keys = ON")
        if conn.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise ConnectionConfigurationError("foreign_keys could not be enabled")
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        conn.execute("PRAGMA synchronous = FULL")
        if conn.execute("PRAGMA busy_timeout").fetchone() != (busy_timeout_ms,):
            raise ConnectionConfigurationError("busy_timeout was not applied")
        if conn.execute("PRAGMA synchronous").fetchone() != (2,):
            raise ConnectionConfigurationError("synchronous=FULL was not applied")
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        if mode == "read_only":
            conn.execute("PRAGMA query_only = ON")
            if conn.execute("PRAGMA query_only").fetchone() != (1,):
                raise ConnectionConfigurationError("query_only could not be enabled")
        else:
            expected = "memory" if memory else "delete"
            if journal != expected:
                raise ConnectionConfigurationError(f"Unsupported writable journal mode: {journal}")
            if conn.execute(f"PRAGMA journal_mode = {expected}").fetchone() != (expected,):
                raise ConnectionConfigurationError("Journal configuration failed")
    except (OSError, ValueError, sqlite3.Error, ConnectionConfigurationError) as error:
        if conn is not None:
            conn.close()
        if isinstance(error, ConnectionConfigurationError):
            raise
        raise ConnectionConfigurationError(f"Cannot open/configure canonical SQLite: {error}") from error
    try:
        yield conn
    finally:
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        finally:
            conn.close()
