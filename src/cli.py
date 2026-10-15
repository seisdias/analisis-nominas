"""Minimal read-only payroll CLI. Run ./nominas or python -m src.cli."""
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import click

from src.canonical_inspection import CanonicalInspector, InspectionError, open_inspector
from src.cli_config import Configuration, ConfigurationError, load_config


def _text(value: object) -> str:
    # Documentary text must not inject terminal controls or extra output lines.
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def _configuration() -> Configuration:
    try:
        return load_config()
    except ConfigurationError as error:
        raise click.ClickException(str(error)) from error


@contextmanager
def _inspector(config: Configuration) -> Iterator[CanonicalInspector]:
    if not config.database.is_file():
        raise click.ClickException('Base no disponible: comprueba la ruta configurada y los permisos. '
                                   'No se crea ninguna base.')
    try:
        with open_inspector(config.database) as inspector:
            yield inspector
    except InspectionError as error:
        raise click.ClickException('No se pudo consultar la base: requiere esquema canónico v8, '
                                   'integridad válida y journal DELETE. Comprueba acceso y esquema; '
                                   'no se crean ni migran bases.') from error


def _amount(value: dict[str, Any]) -> str:
    status = value['status']
    if status != 'certified' or value.get('amount') is None:
        reason = {'no_observation': 'sin observación', 'ambiguous': 'ambiguo',
                  'not_certified': 'certificación no superada'}.get(status, 'importe ausente')
        return f'No certificado ({reason})'
    amount = value['amount']
    number = format(amount.to_decimal(), f',.{max(2, amount.scale)}f')
    number = number.translate(str.maketrans(',.', '.,'))
    currency = value.get('currency')
    unit = _text(currency.code) if currency is not None else 'divisa no documentada'
    return f'{number} ({unit}; certificado)'


def _documents(company: str | None, year: int | None, month: int | None = None,
               *, detail: bool = False) -> None:
    with _inspector(_configuration()) as inspector:
        rows = inspector.documents(company=company, year=year, month=month)
    rows.sort(key=lambda row: (row['year'] is None, row['year'] or 0,
                              row['month'] is None, row['month'] or 0, row['document_id']))
    click.echo(f'Documentos: {len(rows)}')
    for row in rows:
        period = f'{row["year"] or "?"}/{row["month"]:02d}' if row['month'] else f'{row["year"] or "?"}/?'
        click.echo(f'{period} | {_text(row["company_text"] or "Empresa ausente o ambigua")} | '
                   f'Bruto: {_amount(row["gross"])} | Neto: {_amount(row["net"])}')
        if detail:
            click.echo(f'  Documento: {_text(row["document_id"])}')
            click.echo('  Periodo documental; no presupone liquidación ni devengo.')
    if not rows:
        click.echo('No hay documentos para los filtros seleccionados.')
    click.echo('Certificar un importe no permite sumarlo. Sin agregaciones ni cambios de elegibilidad.')


@click.group(name='nominas')
def cli() -> None:
    """Análisis-Nóminas v0.1: consulta documental de solo lectura."""


@cli.command()
def empresas() -> None:
    """Empresas por denominación documental exacta, sin inferir identidad."""
    with _inspector(_configuration()) as inspector:
        result = inspector.companies()
    for item in result['companies']:
        click.echo(f'{_text(item["company_text"])} | Documentos: {item["documents"]}')
    click.echo(f'Documentos con empresa ausente o ambigua: {len(result["unassigned_documents"])}')


@cli.command()
@click.option('--empresa', help='Denominación documental exacta.')
@click.option('--anio', type=click.IntRange(1, 9999))
def listar(empresa: str | None, anio: int | None) -> None:
    """Listar documentos con bruto y neto certificados, sin sumar importes."""
    _documents(empresa, anio)


@cli.command()
@click.option('--empresa', required=True, help='Denominación documental exacta.')
@click.option('--anio', required=True, type=click.IntRange(1, 9999))
@click.option('--mes', required=True, type=click.IntRange(1, 12))
def ver(empresa: str, anio: int, mes: int) -> None:
    """Detalle documental de todos los documentos que coincidan con el periodo."""
    _documents(empresa, anio, mes, detail=True)


@cli.command()
def estado() -> None:
    """Base activa, integridad y contadores; sin importes ni rutas privadas."""
    config = _configuration()
    with _inspector(config) as inspector:
        result = inspector.summary()
    click.echo(f'Base activa: {_text(config.database.name)} (origen: {config.source})')
    click.echo('Esquema: v8 | Integridad y claves foráneas: OK | Solo lectura')
    for table, count in result['counts'].items():
        click.echo(f'{table}: {count}')
    for eligibility, count in result['states']['economic_observations.eligibility'].items():
        click.echo(f'Elegibilidad {_text(eligibility)}: {count}')


@cli.command(name='config')
def show_config() -> None:
    """Mostrar rutas resueltas (pueden ser privadas); no abrir la base."""
    config = _configuration()
    click.echo(f'Origen de base: {config.source}')
    click.echo(f'Base SQLite: {_text(config.database)}')
    click.echo(f'Directorio de nóminas: {_text(config.payroll_directory or "No configurado")}')


if __name__ == '__main__':
    cli()
