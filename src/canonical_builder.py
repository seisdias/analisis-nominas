"""Run: python -m src.canonical_builder --config build.json --output NEW.sqlite."""
import sqlite3
from pathlib import Path

import click

from src.canonical_build import BuildError, BuildReport, build, load_config
from src.persistence import CanonicalSQLiteError


def _report(report: BuildReport) -> None:
    click.echo(f'inventoried: {report.inventoried}')
    click.echo(f'processed: {report.ingestion.processed}')
    click.echo(f'skipped: {report.ingestion.skipped}')
    click.echo(f'failed: {report.ingestion.failed}')
    click.echo(f'schema version: {report.schema_version}')


@click.command()
@click.option('--config', 'config_path', required=True,
              type=click.Path(path_type=Path, exists=True, dir_okay=False),
              help='Versioned JSON build plan. Relative sources resolve from this file.')
@click.option('--output', required=True, type=click.Path(path_type=Path, dir_okay=False),
              help='New SQLite path in an existing directory. Never overwrites, no force mode.')
def cli(config_path: Path, output: Path) -> None:
    """Build a persistent canonical v8 SQLite using the certified ingestion pipeline.

    Explicit exclusions only. No new economic policy. Publication requires zero
    failed items and verified schema; failed provisional builds are discarded.
    """
    try:
        report = build(load_config(config_path), output)
    except BuildError as error:
        if error.report is not None:
            _report(error.report)
        raise click.ClickException(str(error)) from error
    except (OSError, ValueError, TypeError, sqlite3.Error, CanonicalSQLiteError) as error:
        raise click.ClickException(f'Build not published: {error}') from error
    _report(report)


if __name__ == '__main__':
    cli()
