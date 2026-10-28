"""Small shared display helpers; full identities remain in the source records."""
from typing import Any

from src.canonical.values import CanonicalValue, ExactDecimal, ValueState


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


VALUE_STATES = {
    ValueState.PRESENT: 'Disponible', ValueState.UNKNOWN: 'Desconocido',
    ValueState.NOT_EXTRACTED: 'No extraído', ValueState.NOT_PRESENT: 'No presente',
    ValueState.TECHNICAL_NULL: 'Nulo técnico', ValueState.NOT_APPLICABLE: 'No aplicable',
    ValueState.UNRELIABLE: 'No fiable',
}


def canonical_candidate_text(value: CanonicalValue, *, monetary: bool = False) -> str:
    """Original candidate, for provenance only when the state is not PRESENT."""
    raw = value.value
    if raw is None:
        return 'Sin valor'
    if isinstance(raw, ExactDecimal):
        places = max(raw.scale, 2) if monetary else raw.scale
        text = f'{raw.to_decimal():,.{places}f}'.translate(str.maketrans(',.', '.,'))
    else:
        text = str(raw)
    return text + (' ' + value.currency.code if value.currency else '')


def canonical_value_text(value: CanonicalValue, *, monetary: bool = False) -> str:
    """Documentary value/state. Never supplies a currency or an absent amount."""
    return (canonical_candidate_text(value, monetary=monetary) if value.state == ValueState.PRESENT
            else VALUE_STATES[value.state])
