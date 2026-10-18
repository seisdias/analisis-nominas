"""Shared CLI/GUI configuration, anchored to the source repository."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    """Invalid or absent local configuration (safe to show in either interface)."""


@dataclass(frozen=True)
class Configuration:
    database: Path
    payroll_directory: Path | None
    source: str
    withheld_document_ids: tuple[str, ...] = ()


def _path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ConfigurationError(f'Configuración: {label} debe ser una ruta no vacía.')
    path = Path(value).expanduser()
    return (REPOSITORY_ROOT / path).resolve()


def load_config(*, database: str | Path | None = None,
                payroll_directory: str | Path | None = None) -> Configuration:
    """Explicit arguments > environment > TOML; no implicit database default.

    Keep this module/import path for CLI compatibility. The optional documentary
    directory defaults to None and has no environment override. No filesystem writes.
    """
    file = REPOSITORY_ROOT / 'config.toml'
    try:
        try:
            data = tomllib.loads(file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            data = {}
        paths = data.get('paths', {})
        if not isinstance(paths, dict):
            raise ConfigurationError('Configuración: [paths] debe ser una tabla TOML.')
        presentation = data.get('presentation', {})
        if not isinstance(presentation, dict):
            raise ConfigurationError('Configuración: [presentation] debe ser una tabla TOML.')
        withheld = presentation.get('withheld_document_ids', [])
        if not isinstance(withheld, list) or any(not isinstance(v, str) or not v.strip() for v in withheld):
            raise ConfigurationError('Configuración: withheld_document_ids debe ser una lista de identificadores.')
        environment_database = os.environ.get('ANALISIS_NOMINAS_CANONICAL_DB')
        source = ('argumento explícito' if database is not None else
                  'ANALISIS_NOMINAS_CANONICAL_DB' if environment_database else 'config.toml')
        database_value = (str(database) if database is not None else
                          environment_database or paths.get('database'))
        if database_value is None:
            raise ConfigurationError('Falta configuración: crea config.toml desde config.example.toml '
                                     'o define ANALISIS_NOMINAS_CANONICAL_DB.')
        payroll = (str(payroll_directory) if payroll_directory is not None else
                   paths.get('payroll_directory'))
        return Configuration(
            _path(database_value, 'database'),
            _path(payroll, 'payroll_directory') if payroll is not None else None,
            source,
            tuple(sorted(set(withheld))),
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, RuntimeError) as error:
        raise ConfigurationError('No se puede leer config.toml o sus rutas. '
                                 'Comprueba permisos y sintaxis TOML.') from error
