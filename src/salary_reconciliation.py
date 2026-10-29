"""Exact, non-persistent diagnostics. No production completeness contract is enabled."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from src.canonical.values import ExactDecimal, ValueState
from src.document_concepts import ExtractionConcepts, FactEvidence, project_extraction
from src.economic_classification import Knowledge


class Status(StrEnum):
    RECONCILED = "Conciliado con evidencia suficiente"
    DIFFERENCE = "Diferencia detectada"
    INCOMPLETE = "Desglose incompleto"
    UNAVAILABLE = "No evaluable"
    CONFLICT = "Conflicto documental"


@dataclass(frozen=True)
class ReconciliationContract:
    """Trusted caller's reviewed extraction contract, NOT a numerical equality flag.

    A nonempty evidence reference must document coverage, signs and units for the
    exact extractor revision. UI supplies none: persisted evidence currently does
    not establish these guarantees. Never construct from an observed sum/residue.
    """

    extractor_name: str
    extractor_revision: str
    evidence_reference: str
    earnings_complete: bool = False
    deductions_complete: bool = False
    signed_columns: bool = False
    net_relation: bool = False
    same_unit: bool = False


@dataclass(frozen=True)
class Diagnostic:
    document_id: str
    version_id: str
    extraction_id: str
    magnitude: str
    status: Status
    knowledge: Knowledge
    formula: str
    participants: tuple[FactEvidence, ...]
    target: FactEvidence | None
    calculated: Decimal | None
    difference: Decimal | None
    reason: str
    contract_reference: str | None


def _decimal(coefficient: int, scale: int) -> Decimal:
    # Decimal tuple construction does not use the ambient precision/context.
    return Decimal((int(coefficient < 0), tuple(map(int, str(abs(coefficient)))), -scale))


def _calculate(
    parts: tuple[FactEvidence, ...], target: FactEvidence, *, subtract: bool = False
) -> tuple[Decimal, Decimal]:
    values = [f.fact.value.value for f in (*parts, target)]
    assert all(isinstance(v, ExactDecimal) for v in values)
    exact = [v for v in values if isinstance(v, ExactDecimal)]
    scale = max(v.scale for v in exact)
    coefficients = [v.coefficient * 10 ** (scale - v.scale) for v in exact]
    calculated = (coefficients[0] - coefficients[1]) if subtract else sum(coefficients[:-1])
    return _decimal(calculated, scale), _decimal(calculated - coefficients[-1], scale)


def reconcile(
    e: ExtractionConcepts, contract: ReconciliationContract | None = None
) -> tuple[Diagnostic, ...]:
    """Diagnose only this extraction/version; never import certified totals elsewhere."""
    results = []
    facts = {f.fact.fact_id: f for f in e.facts}
    duplicate_occurrences = len({c.occurrence for c in e.concepts}) != len(e.concepts)
    mixed_vocabulary = len({c.occurrence.split("conceptos")[0] for c in e.concepts}) > 1
    bad_scope = any(
        (c.document_id, c.version_id, c.extraction_id)
        != (e.document_id, e.version_id, e.extraction_id)
        or any(
            f.fact.extraction_id != e.extraction_id or facts.get(f.fact.fact_id) != f
            for _, f in c.attributes
        )
        for c in e.concepts
    ) or any(f.fact.extraction_id != e.extraction_id for f in e.facts)
    # A complete contract cannot authorize a caller-truncated projection. Reuse
    # the canonical occurrence reconstruction against the full supplied evidence.
    try:
        reconstructed = project_extraction(
            e.document_id,
            e.version_id,
            e.extraction_id,
            tuple(f.fact for f in e.facts),
            pages={f.fact.fact_id: f.pages for f in e.facts},
        )
        bad_scope = bad_scope or reconstructed.concepts != tuple(
            sorted(e.concepts, key=lambda c: c.occurrence)
        )
    except ValueError:
        bad_scope = True
    totals = {
        name: tuple(f for f in e.facts if f.fact.fact_key in ("nomina." + name, "payload/" + name))
        for name in ("total_devengado", "total_deducir", "liquido_percibir")
    }
    groups: dict[str, list[FactEvidence]] = {"devengos": [], "deducciones": []}
    unknown_column = False
    missing_amount = False
    for c in sorted(e.concepts, key=lambda c: c.occurrence):
        column = c.get("columna")
        amount = c.get("importe")
        if column is None or column.fact.value.state != ValueState.PRESENT:
            unknown_column = True
        elif column.fact.value.value in groups:
            if amount is None:
                missing_amount = True
            else:
                groups[str(column.fact.value.value)].append(amount)
        elif column.fact.value.value not in ("bases", "informacion"):
            unknown_column = True
    formulas = (
        (
            "Devengos",
            "total_devengado",
            "Suma de partidas de devengos − total devengado",
            tuple(groups["devengos"]),
        ),
        (
            "Deducciones",
            "total_deducir",
            "Suma de partidas de deducciones − total deducciones",
            tuple(groups["deducciones"]),
        ),
        (
            "Bruto/neto",
            "liquido_percibir",
            "Total devengado − total deducciones − neto",
            tuple(t[0] for n in ("total_devengado", "total_deducir") if len(t := totals[n]) == 1),
        ),
    )
    for label, name, formula, parts in formulas:
        targets = totals[name]
        target = targets[0] if len(targets) == 1 else None
        status = Status.UNAVAILABLE
        reason = "Falta un total documental comparable"
        calculated = difference = None
        enabled = bool(
            contract
            and (
                (
                    contract.earnings_complete
                    if label == "Devengos"
                    else contract.deductions_complete
                )
                if label != "Bruto/neto"
                else contract.earnings_complete
                and contract.deductions_complete
                and contract.net_relation
            )
        )
        support = (*parts, *((target,) if target else ()))
        # Net requires valid coverage and monetary rows too, not just three totals.
        checked = (
            (*support, *groups["devengos"], *groups["deducciones"])
            if label == "Bruto/neto"
            else support
        )
        invalid_values = any(
            f.fact.value.state != ValueState.PRESENT
            or not isinstance(f.fact.value.value, ExactDecimal)
            for f in checked
        )
        currencies = {
            f.fact.value.currency.code if f.fact.value.currency else None for f in checked
        }
        if (
            bad_scope
            or duplicate_occurrences
            or mixed_vocabulary
            or any(len(v) > 1 for v in totals.values())
        ):
            status = Status.CONFLICT
            reason = "Procedencia, ocurrencias o totales alternativos no inequívocos"
        elif contract and (contract.extractor_name, contract.extractor_revision) != (
            e.extractor_name,
            e.extractor_revision,
        ):
            status = Status.CONFLICT
            reason = "El contrato no corresponde a esta extracción"
        elif not target or (label == "Bruto/neto" and len(parts) != 2):
            pass
        elif not e.concepts or unknown_column or missing_amount:
            status = Status.INCOMPLETE
            reason = "Lista ausente, columna desconocida o partida sin importe"
        elif invalid_values:
            reason = "Importes desconocidos, no fiables o no monetarios"
        elif not enabled or not contract or not contract.evidence_reference.strip():
            status = Status.INCOMPLETE
            reason = "Completitud y aditividad no acreditadas: la igualdad numérica no basta"
        elif not contract.signed_columns:
            reason = "Convención de signos no acreditada"
        elif len(currencies) != 1 or (None in currencies and not contract.same_unit):
            reason = "Unidad monetaria común no acreditada; no se infiere EUR"
        elif not parts:
            status = Status.INCOMPLETE
            reason = "No se convierte un grupo ausente en cero"
        else:
            calculated, difference = _calculate(parts, target, subtract=label == "Bruto/neto")
            status = Status.RECONCILED if difference == 0 else Status.DIFFERENCE
            reason = (
                "Igualdad exacta bajo el contrato explícito"
                if difference == 0
                else "Diferencia no explicada; no se atribuye a una categoría económica"
            )
        results.append(
            Diagnostic(
                e.document_id,
                e.version_id,
                e.extraction_id,
                label,
                status,
                Knowledge.CALCULATED if difference is not None else Knowledge.UNDETERMINABLE,
                formula,
                parts,
                target,
                calculated,
                difference,
                reason,
                contract.evidence_reference if contract else None,
            )
        )
    return tuple(results)
