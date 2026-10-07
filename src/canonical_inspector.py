"""Run: python -m src.canonical_inspector --db DATABASE COMMAND."""
import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import click

from src.canonical.certification import CertificationRequirements
from src.canonical.values import ExactDecimal
from src.canonical_inspection import InspectionError, open_inspector


def _render(value: Any, indent: str = '') -> None:
    """Stable terminal text; escape documentary control characters, no export format."""
    if is_dataclass(value) and not isinstance(value, type):
        value = {f.name: getattr(value, f.name) for f in fields(value)}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, ExactDecimal):
                click.echo(f'{indent}{key}: {item.to_decimal():f}')
            elif is_dataclass(item) or isinstance(item, (dict, tuple, list)):
                click.echo(f'{indent}{key}:')
                _render(item, indent + '  ')
            else:
                click.echo(f'{indent}{key}: {json.dumps(item, ensure_ascii=False)}')
    elif isinstance(value, (tuple, list)):
        if not value:
            click.echo(indent + '(none)')
        for index, item in enumerate(value):
            click.echo(f'{indent}[{index}]')
            _render(item, indent + '  ')
    else:
        click.echo(indent + json.dumps(value, ensure_ascii=False))


def _run(db: Path, method: str, *args: Any, **kwargs: Any) -> None:
    try:
        with open_inspector(db) as inspector:
            _render(getattr(inspector, method)(*args, **kwargs))
    except InspectionError as error:
        raise click.ClickException(str(error)) from error


@click.group()
@click.option('--db', type=click.Path(path_type=Path, dir_okay=False), required=True,
              help='Explicit canonical v8 SQLite path. Read-only; never created or migrated.')
@click.pass_context
def cli(ctx: click.Context, db: Path) -> None:
    """Read-only canonical diagnostics. No economic aggregation or version selection."""
    ctx.obj = db


@cli.command()
@click.pass_obj
def summary(db: Path) -> None:
    """Structural counts and stored states (not economic KPIs)."""
    _run(db, 'summary')


@cli.command()
@click.option('--magnitude', help='Exact stored magnitude.')
@click.option('--economic-status', help='Exact stored economic status.')
@click.option('--eligibility', help='Exact stored eligibility; never promoted.')
@click.option('--limit', type=click.IntRange(1, 1000), default=50, show_default=True)
@click.pass_obj
def observations(db: Path, magnitude: str | None, economic_status: str | None,
                 eligibility: str | None, limit: int) -> None:
    """List observations in ID order; no candidate selection."""
    _run(db, 'observations', magnitude=magnitude, economic_status=economic_status,
         eligibility=eligibility, limit=limit)


@cli.command()
@click.argument('observation_id')
@click.option('--require-currency', is_flag=True)
@click.option('--require-employer', is_flag=True)
@click.option('--require-liquidation-period', is_flag=True)
@click.option('--require-accrual-interval', is_flag=True)
@click.option('--require-payment-date', is_flag=True)
@click.pass_obj
def explain(db: Path, observation_id: str, require_currency: bool, require_employer: bool,
            require_liquidation_period: bool, require_accrual_interval: bool,
            require_payment_date: bool) -> None:
    """Show certification and provenance. Unrequested context is NOT_EVALUATED.

    Certification does not imply additivity. No relation/version is resolved.
    """
    _run(db, 'explain', observation_id, CertificationRequirements(
        currency=require_currency, employer=require_employer,
        liquidation_period=require_liquidation_period, accrual_interval=require_accrual_interval,
        payment_date=require_payment_date))


@cli.command()
@click.option('--extraction-id')
@click.option('--fact-key', help='Exact documentary key.')
@click.option('--value-state')
@click.option('--limit', type=click.IntRange(1, 1000), default=50, show_default=True)
@click.pass_obj
def facts(db: Path, extraction_id: str | None, fact_key: str | None,
          value_state: str | None, limit: int) -> None:
    """List documentary facts in ID order; no interpretation."""
    _run(db, 'facts', extraction_id=extraction_id, fact_key=fact_key,
         value_state=value_state, limit=limit)


@cli.command()
@click.argument('document_id')
@click.pass_obj
def document(db: Path, document_id: str) -> None:
    """Show all document versions, physical sources, pages and extractions."""
    _run(db, 'document', document_id)


if __name__ == '__main__':
    cli()
