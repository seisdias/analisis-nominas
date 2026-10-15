"""CLI contract against synthetic v8 databases; no private inputs."""
import sqlite3

import pytest
from click.testing import CliRunner

from src.cli import cli
from src.cli_config import load_config
from src.persistence import open_database

pytest_plugins = ["tests.integration.persistence.test_canonical_inspector"]


@pytest.fixture
def configured(tmp_path, monkeypatch):
    import src.cli_config as config
    monkeypatch.setattr(config, 'REPOSITORY_ROOT', tmp_path)
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)
    path = tmp_path / 'canonical.sqlite'
    with open_database(path, mode='create'):
        pass
    (tmp_path / 'config.toml').write_text('[paths]\ndatabase = "canonical.sqlite"\n')
    return path


@pytest.mark.parametrize('args', [['empresas'], ['listar'],
    ['ver', '--empresa', 'Synthetic', '--anio', '2025', '--mes', '1'], ['estado'], ['config']])
def test_commands_read_only(configured, args):
    before = configured.read_bytes()
    files = set(configured.parent.iterdir())
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert configured.read_bytes() == before
    assert set(configured.parent.iterdir()) == files


def test_relative_paths_ignore_cwd(configured, monkeypatch, tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_config().database == configured
    assert CliRunner().invoke(cli, ['estado']).exit_code == 0


def test_environment_override(configured, monkeypatch):
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', 'override.sqlite')
    assert load_config().database == configured.parent / 'override.sqlite'


@pytest.mark.parametrize('content', [None, '', '[paths]\ndatabase = 3', '[invalid'])
def test_bad_config(configured, content):
    path = configured.parent / 'config.toml'
    path.unlink()
    if content is not None:
        path.write_text(content)
    result = CliRunner().invoke(cli, ['estado'])
    assert result.exit_code != 0
    assert 'config' in result.output.lower()
    assert str(configured.parent) not in result.output


@pytest.mark.parametrize('kind', ['missing', 'invalid', 'wrong_schema'])
def test_bad_database(configured, kind):
    configured.unlink()
    if kind == 'invalid':
        configured.write_bytes(b'private invalid contents')
    elif kind == 'wrong_schema':
        with sqlite3.connect(configured) as connection:
            connection.execute('CREATE TABLE unrelated (id INTEGER)')
    before = configured.read_bytes() if configured.exists() else None
    result = CliRunner().invoke(cli, ['estado'])
    assert result.exit_code != 0
    assert 'base' in result.output.lower()
    assert str(configured) not in result.output
    assert (configured.read_bytes() if configured.exists() else None) == before


def test_help_without_config():
    result = CliRunner().invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert all(name in result.output for name in ('empresas', 'listar', 'ver', 'estado', 'config'))


def test_certified_detail_and_exact_filters(configured, dataset):
    from src.canonical.facts import DocumentaryFact, FactDraft
    from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
    from src.persistence.economics import EconomicRepository
    with sqlite3.connect(configured) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        for key, value in (('empresa', 'Synthetic'), ('anio', ExactDecimal(2025, 0)),
                           ('mes', ExactDecimal(1, 0)), ('cif', 'SECRET_PERSONAL_ID')):
            repo.register_fact(DocumentaryFact.from_draft(dataset[4][0].extraction_id,
                FactDraft('nomina.' + key, CanonicalValue(state=ValueState.PRESENT, value=value))))
    before = configured.read_bytes()
    runner = CliRunner()
    result = runner.invoke(cli, ['ver', '--empresa', 'Synthetic', '--anio', '2025', '--mes', '1'])
    assert result.exit_code == 0, result.output
    assert 'Documentos: 1' in result.output
    assert result.output.count('201,53') == 2
    assert 'certificado' in result.output
    assert dataset[1].document_id in result.output
    assert 'SECRET_PERSONAL_ID' not in result.output
    assert str(configured.parent) not in result.output
    assert 'Documentos: 0' in runner.invoke(cli, ['listar', '--empresa', 'synthetic']).output
    assert configured.read_bytes() == before


@pytest.mark.parametrize('status', ['no_observation', 'not_certified', 'ambiguous'])
def test_uncertified_amount_never_disclosed(status):
    from src.canonical.values import ExactDecimal
    from src.cli import _amount
    text = _amount({'status': status, 'amount': ExactDecimal(99999, 2)})
    assert 'No certificado' in text
    assert '999' not in text


def test_config_optional_directory_and_environment_without_file(configured, monkeypatch):
    file = configured.parent / 'config.toml'
    file.write_text('[paths]\ndatabase = "canonical.sqlite"\npayroll_directory = "documents"\n')
    assert load_config().payroll_directory == configured.parent / 'documents'
    file.unlink()
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(configured))
    assert CliRunner().invoke(cli, ['estado']).exit_code == 0


def test_terminal_controls_escaped():
    from src.cli import _text
    assert _text('Company\n\x1b[31m') == r'Company\n\u001b[31m'
