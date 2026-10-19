"""Small shared display helpers; full identities remain in the source records."""
from typing import Any


def short_id(identity: str) -> str:
    identity = identity.rsplit(':sha256:', 1)[-1]
    return identity if len(identity) <= 24 else identity[:12] + '…' + identity[-6:]


def format_period(year: int | None, month: int | None) -> str:
    if year is not None and month is not None:
        return f'{month:02d}/{year:04d}'
    if month is not None:
        return f'{month:02d}/Año ausente o ambiguo'
    return f'Mes ausente o ambiguo/{year or "Año ausente o ambiguo"}'


def friendly_timeline_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = ('Periodo', 'Empresa', 'Categoría', 'Serie', 'Importe', 'Certificación', 'Representación', 'Intervalo documental', 'Documento')
    return [{key: short_id(row[key]) if key == 'Documento' else row[key]
             for key in columns if key in row} for row in rows]
