"""Run: python -m src.canonical_inspector --db DATABASE COMMAND."""
import csv
import json
import os
from dataclasses import fields, is_dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
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


def _export_documents(db: Path, destination: Path, rows: list[dict[str, Any]]) -> None:
    """Publish a complete CSV atomically; never replace the inspected database."""
    temporary: Path | None = None
    try:
        database = db.resolve()
        target = destination.resolve()
        if (target == database or (target.exists() and target.samefile(database))
                or target in {Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal')}):
            raise click.ClickException('CSV destination must not be the SQLite database or its sidecars')
        columns = ['document_id', 'company_text', 'year', 'month', 'gross_status',
                   'gross_amount', 'gross_currency', 'net_status', 'net_amount', 'net_currency']
        with NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                dir=target.parent, prefix='.documents-', suffix='.tmp',
                                delete=False) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter=';')
            writer.writeheader()
            for row in rows:
                record = {key: row[key] for key in columns[:4]}
                for field in ('gross', 'net'):
                    value = row[field]
                    record[field + '_status'] = value['status']
                    certified = value['status'] == 'certified'
                    amount = value.get('amount') if certified else None
                    record[field + '_amount'] = f'{amount.to_decimal():f}' if amount is not None else None
                    currency = value.get('currency') if certified else None
                    record[field + '_currency'] = currency.code if currency is not None else None
                writer.writerow(record)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except (OSError, UnicodeError, csv.Error) as error:
        raise click.ClickException(f'Cannot write CSV: {error}') from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@click.group()
@click.option('--db', type=click.Path(path_type=Path, dir_okay=False), required=True,
              help='Explicit canonical v8 SQLite path. Read-only; never created or migrated.')
@click.pass_context
def cli(ctx: click.Context, db: Path) -> None:
    """Read-only canonical diagnostics. No economic aggregation or version selection."""
    ctx.obj = db


@cli.command()
@click.pass_obj
def companies(db: Path) -> None:
    """Empresas por texto documental exacto y documentos lógicos, sin CIF ni salarios.

    Exige concordancia entre versiones/extracciones; discrepancias o ausencias
    quedan sin asignar. No identifica empresas mediante employer_id.
    """
    _run(db, 'companies')


@cli.command()
@click.pass_obj
def coverage(db: Path) -> None:
    """Cobertura documental por empresa; conteos, sin sumas económicas ni selección."""
    _run(db, 'coverage')


@cli.command()
@click.option('--company', help='Denominación documental exacta, sin normalización.')
@click.option('--year', type=click.IntRange(1, 9999), help='Año documental.')
@click.option('--month', type=click.IntRange(1, 12), help='Mes documental (1–12).')
@click.option('--csv', 'csv_path', type=click.Path(path_type=Path, dir_okay=False),
              help='Exportar CSV UTF-8 con BOM y delimitador ;. Reemplaza el destino al terminar.')
@click.pass_obj
def documents(db: Path, company: str | None, year: int | None, month: int | None,
              csv_path: Path | None) -> None:
    """Documentos lógicos por ID; sin sumas, CIF ni rutas privadas.

    Los filtros exigen concordancia del campo entre versiones/extracciones.
    Sin filtros se incluyen ausencias y discrepancias con valor null y diagnóstico.
    Bruto/neto: certified permite importe; no_observation, not_certified o ambiguous
    no lo permiten. Varias observaciones son ambiguas incluso si coinciden.
    Certificación documental no implica uso económico ni aditividad.
    """
    if csv_path is None:
        _run(db, 'documents', company=company, year=year, month=month)
        return
    try:
        with open_inspector(db) as inspector:
            rows = inspector.documents(company=company, year=year, month=month)
        _export_documents(db, csv_path, rows)
    except InspectionError as error:
        raise click.ClickException(str(error)) from error


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
