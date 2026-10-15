"""Local CLI configuration, anchored to the source repository."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    """Invalid or absent local configuration (safe to show in a terminal)."""


@dataclass(frozen=True)
class Configuration:
    database: Path
    payroll_directory: Path | None
    source: str


def _path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ConfigurationError(f'Configuración: {label} debe ser una ruta no vacía.')
    path = Path(value).expanduser()
    return (REPOSITORY_ROOT / path).resolve()


def load_config() -> Configuration:
    """Environment overrides the database only; never writes files or directories."""
    file = REPOSITORY_ROOT / 'config.toml'
    try:
        data = tomllib.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
        paths = data.get('paths', {})
        if not isinstance(paths, dict):
            raise ConfigurationError('Configuración: [paths] debe ser una tabla TOML.')
        database = os.environ.get('ANALISIS_NOMINAS_CANONICAL_DB') or paths.get('database')
        if database is None:
            raise ConfigurationError('Falta configuración: crea config.toml desde config.example.toml '
                                     'o define ANALISIS_NOMINAS_CANONICAL_DB.')
        payroll = paths.get('payroll_directory')
        return Configuration(
            _path(database, 'database'),
            _path(payroll, 'payroll_directory') if payroll is not None else None,
            'ANALISIS_NOMINAS_CANONICAL_DB'
            if os.environ.get('ANALISIS_NOMINAS_CANONICAL_DB') else 'config.toml',
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RuntimeError) as error:
        raise ConfigurationError('No se puede leer config.toml o sus rutas. '
                                 'Comprueba permisos y sintaxis TOML.') from error
