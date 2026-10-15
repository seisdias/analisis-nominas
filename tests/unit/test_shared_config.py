"""Shared configuration precedence; no local/private configuration is read."""
from pathlib import Path

import pytest

from src.cli_config import ConfigurationError, load_config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr('src.cli_config.REPOSITORY_ROOT', tmp_path)
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)


def test_explicit_environment_file_and_defaults(tmp_path, monkeypatch):
    (tmp_path / 'config.toml').write_text(
        '[paths]\ndatabase="file.sqlite"\npayroll_directory="pdfs"\n')
    config = load_config()
    assert config.database == tmp_path / 'file.sqlite'
    assert config.source == 'config.toml'
    assert config.payroll_directory == tmp_path / 'pdfs'
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', 'env.sqlite')
    assert load_config().database == tmp_path / 'env.sqlite'
    assert load_config().source == 'ANALISIS_NOMINAS_CANONICAL_DB'
    config = load_config(database=Path('explicit.sqlite'), payroll_directory='explicit-pdfs')
    assert config.database == tmp_path / 'explicit.sqlite'
    assert config.source == 'argumento explícito'
    assert config.payroll_directory == tmp_path / 'explicit-pdfs'
    (tmp_path / 'config.toml').unlink()
    assert load_config().payroll_directory is None
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB')
    with pytest.raises(ConfigurationError, match='Falta configuración'):
        load_config()


@pytest.mark.parametrize('content', ['[broken', '[paths]\ndatabase=3', '[paths]\ndatabase=""',
                                     'paths=3', '[paths]\ndatabase="db"\npayroll_directory=3'])
def test_invalid_config_is_safe(tmp_path, content):
    (tmp_path / 'config.toml').write_text(content)
    with pytest.raises(ConfigurationError) as error:
        load_config()
    assert str(tmp_path) not in str(error.value)


def test_paths_from_root_not_working_directory(tmp_path, monkeypatch):
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_config(database='relative.sqlite').database == tmp_path / 'relative.sqlite'
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', 'relative.sqlite')
    assert load_config().database == tmp_path / 'relative.sqlite'


def test_unreadable_config_redacts_os_error(tmp_path, monkeypatch):
    (tmp_path / 'config.toml').touch()
    def denied(*args, **kwargs):
        raise PermissionError('SENSITIVE_PATH')
    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(ConfigurationError) as error:
        load_config()
    assert 'SENSITIVE_PATH' not in str(error.value)


def test_absolute_and_home_paths(tmp_path):
    absolute = tmp_path / 'absolute.sqlite'
    assert load_config(database=absolute).database == absolute
    # expanduser uses the process home, so compare to Path's own expansion.
    assert load_config(database='~/canonical.sqlite').database == Path('~/canonical.sqlite').expanduser()


def test_malformed_toml_not_silently_ignored_by_override(tmp_path, monkeypatch):
    (tmp_path / 'config.toml').write_text('[broken')
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', 'env.sqlite')
    with pytest.raises(ConfigurationError):
        load_config(database='explicit.sqlite')
