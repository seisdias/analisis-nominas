"""Real SQLite failures, isolated storage; no private records."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models.nomina import Nomina
from src.services.database_service import DatabaseService


@pytest.mark.parametrize("memory", [False, True], ids=["file", "shared-memory"])
@pytest.mark.parametrize("failure", ["insert", "commit"])
def test_failed_write_rolls_back_and_manages_connection(tmp_path: Path, memory: bool, failure: str) -> None:
    service = DatabaseService(":memory:" if memory else str(tmp_path / "synthetic.sqlite"))
    service.init_db()
    states_at_close = []

    class ObservedConnection(sqlite3.Connection):
        def close(self) -> None:
            states_at_close.append(self.in_transaction)
            super().close()

    conn = service._shared_conn if memory else sqlite3.connect(service.db_path, factory=ObservedConnection)
    assert conn is not None
    conn.execute("PRAGMA foreign_keys = ON")
    if failure == "insert":
        conn.execute("""CREATE TEMP TRIGGER reject_synthetic BEFORE INSERT ON documentos
                        WHEN NEW.id = 'bad' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    else:
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child (id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)")
        conn.execute("""CREATE TEMP TRIGGER reject_synthetic AFTER INSERT ON documentos
                        WHEN NEW.id = 'bad' BEGIN INSERT INTO child VALUES (1); END""")
    conn.commit()
    bad = Nomina(id="bad", anio=2099, mes=1, periodo="2099-01", empresa="Synthetic", cif="TEST")
    try:
        with patch.object(service, "_get_connection", return_value=conn):
            with pytest.raises(sqlite3.IntegrityError):
                service.guardar_documento(bad)
        if memory:
            assert not conn.in_transaction
            assert conn.execute("SELECT count(*) FROM documentos").fetchone()[0] == 0
        else:
            assert states_at_close == [False], "Connection must close after transaction rollback"
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
        good = Nomina(id="good", anio=2099, mes=1, periodo="2099-01", empresa="Synthetic", cif="TEST")
        service.guardar_documento(good)
        assert [row["id"] for row in service.obtener_todos()] == ["good"]
    finally:
        # Keep failing pre-fix tests isolated too.
        try:
            conn.rollback()
            conn.close()
        except sqlite3.ProgrammingError:
            pass
