"""C.4.4-A: exact selected-document arithmetic, never annual certification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.annual_summary import AnnualGroup
from src.canonical.values import ExactDecimal


@dataclass(frozen=True)
class DocumentarySum:
    series: str
    status: str
    amount: Decimal | None
    currency: str | None
    included: tuple[str, ...]
    excluded: tuple[tuple[str, str], ...]
    months: tuple[int, ...]
    observations: tuple[str, ...]


def exploratory_sum(
    group: AnnualGroup,
    rows: Sequence[Mapping[str, Any]],
    series: str,
    *,
    document_relations: Sequence[tuple[str, str, str]],
    observation_relations: Sequence[tuple[str, str, str]],
) -> DocumentarySum:
    """Relations include endpoints outside the filter. Never choose a duplicate winner.

    Certified inspector timeline values supply the exact totals and source version.
    C.3 restrictions must already be attached to the annual group. Components are
    deliberately not inputs. Multiple known currencies block all monetary candidates.
    """
    blocked_docs = {i for a, b, kind in document_relations if kind != "complements" for i in (a, b)}
    blocked_obs = {
        i for a, b, kind in observation_relations if kind != "complements" for i in (a, b)
    }
    owners: dict[str, set[str]] = {}
    for row in rows:
        if row["series"] == series and row.get("observation_id"):
            owners.setdefault(row["observation_id"], set()).add(row["document_id"])
    candidates: dict[str, tuple[Decimal, str, str, int]] = {}
    excluded = {}
    for identity, item in sorted({d.record.document_id: d for d in group.documents}.items()):
        matches = []
        for row in rows:
            if row["document_id"] == identity and row["series"] == series and row not in matches:
                matches.append(row)
        reason = item.exclusion
        versions = item.record.document.provenance
        version = versions[0].version_id if len(versions) == 1 else item.version_id
        if not reason and identity in blocked_docs:
            reason = "Relación documental de duplicidad, sustitución o conciliación pendiente"
        if not reason and (not versions or version is None):
            reason = "Sin versión analítica única autorizada"
        if not reason and (item.record.year is None or item.record.month is None):
            reason = "Periodo documental incompleto"
        if not reason and len(matches) != 1:
            reason = "Importe ausente o varias observaciones; no se selecciona una"
        if not reason:
            row = matches[0]
            value = row["value"]
            obs = row.get("observation_id")
            amount = value.get("amount")
            if (
                row.get("document_status") != "certified"
                or value.get("status") != "certified"
                or not isinstance(amount, ExactDecimal)
                or not obs
            ):
                reason = "Importe ausente, desconocido, no fiable o no certificado"
            elif row.get("eligibility") == "excluded":
                reason = "Observación excluida"
            elif tuple(row.get("source_version_ids", ())) != (version,):
                reason = "Soporte incompatible con la versión autorizada"
            elif obs in blocked_obs or len(owners.get(obs, ())) != 1:
                reason = "Observación relacionada o compartida: posible doble cómputo"
            elif value.get("currency") is None:
                reason = "Moneda canónica no acreditada"
            else:
                assert item.record.month is not None
                candidates[identity] = (
                    amount.to_decimal(),
                    value["currency"].code,
                    obs,
                    item.record.month,
                )
        if reason:
            excluded[identity] = reason
    currencies = {v[1] for v in candidates.values()}
    if len(currencies) > 1:
        excluded.update(
            {i: "Monedas acreditadas incompatibles; no se elige una" for i in candidates}
        )
        candidates.clear()
    total = None
    if candidates:
        values = [v[0] for v in candidates.values()]
        # Enough significant places for every original coefficient and the carry.
        with localcontext() as ctx:
            ctx.prec = max(
                28,
                max(v.adjusted() for v in values)
                - min(int(v.as_tuple().exponent) for v in values)
                + len(str(len(values)))
                + 2,
            )
            total = sum(values, Decimal(0))
    status = (
        ("partial" if excluded else "calculable")
        if candidates
        else ("blocked" if group.documents else "empty")
    )
    return DocumentarySum(
        series,
        status,
        total,
        next(iter(currencies)) if candidates else None,
        tuple(candidates),
        tuple(sorted(excluded.items())),
        tuple(sorted({v[3] for v in candidates.values()})),
        tuple(v[2] for v in candidates.values()),
    )
