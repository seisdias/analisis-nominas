"""Freeze boundaries and the complete v8 infrastructure, without real data."""
import ast
from pathlib import Path

from src.canonical.serialization import sha256_bytes
from src.persistence import load_migrations, open_database, verify_schema
from src.persistence.state import OPERATIONAL_COLUMNS

ROOT = Path(__file__).resolve().parents[3]


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_canonical_contracts_do_not_import_infrastructure_models_parsers_or_ui():
    forbidden = ('src.persistence', 'src.models', 'src.parsers', 'src.services', 'sqlite3', 'streamlit', 'app')
    for path in (ROOT/'src/canonical').glob('*.py'):
        assert all(not any(name == prefix or name.startswith(prefix+'.') for prefix in forbidden)
                   for name in imports(path)), path.name


def test_parsers_do_not_import_canonical_persistence_or_ui():
    forbidden = ('src.persistence', 'src.canonical', 'src.services.database_service', 'streamlit', 'app')
    for path in (ROOT/'src/parsers').glob('*.py'):
        assert all(not any(name == prefix or name.startswith(prefix+'.') for prefix in forbidden)
                   for name in imports(path)), path.name


def test_all_eight_migrations_checksums_layers_and_restrictive_foreign_keys():
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, 9))
    with open_database(':memory:', mode='create') as db:
        assert verify_schema(db.connection).current_version == 8
        assert db.connection.execute('SELECT version,checksum FROM schema_migrations ORDER BY version').fetchall() == [
            (m.version, sha256_bytes(m.sql.encode())) for m in migrations]
        tables = {r[0] for r in db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert tables == set(OPERATIONAL_COLUMNS) | {'derived_results', 'derived_inputs'}
        for table in sorted(tables):
            assert all(row[2].upper() != 'REAL' for row in db.connection.execute(f'PRAGMA table_info({table})'))
            assert all(row[5:7] == ('RESTRICT', 'RESTRICT') for row in db.connection.execute(f'PRAGMA foreign_key_list({table})'))
        assert db.connection.execute('PRAGMA foreign_keys').fetchone() == (1,)
        assert db.connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []
