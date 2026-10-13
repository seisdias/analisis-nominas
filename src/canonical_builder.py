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

    ALTEN A.2 projects only single-version documents after complete ingestion
    and an unchanged full inventory check. It adds projection extractions,
    facts and assessments using the existing direct-totals rule. Valid totals
    produce gross/net evidence_only observations, subject to existing
    documentary-value certification; they are not eligible for aggregation.
    Multiversion documents receive no projection or economic observations.

    Ordinary corpora support explicit exclusions. ALTEN forbids them: only
    annual certificates recognized by its processor may be skipped. Other skips
    (including nonextractable PDFs), failures or inventory changes block
    publication. Projection requires a fresh complete build, not incremental
    ingestion; original evidence is preserved.

    Publication requires zero failed items, verified schema and successful
    ALTEN finalization where applicable. Failed provisional builds are discarded.
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
