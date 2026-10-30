"""Reviewed closed-table contracts, independent of numerical reconciliation.

Only pinned production extraction revisions are eligible. The persisted content
hash protects the *whole* projection; it is not a signature proving PDF/OCR truth.
No contract is inferred from company names or a matching sum. ALTEN's legacy
bridge does not identify the original parser revision and is deliberately absent.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from src.canonical.serialization import canonical_sha256
from src.canonical.values import ExactDecimal, ValueState
from src.document_concepts import ExtractionConcepts, FactEvidence, project_extraction
from src.salary_reconciliation import Diagnostic, ReconciliationContract, reconcile


class Section(StrEnum):
    EARNINGS = "devengos"
    DEDUCTIONS = "deducciones"


class Completeness(StrEnum):
    ACCREDITED = "Completitud acreditada"
    NOT_ACCREDITED = "Completitud no acreditada"
    PARTIAL = "Integridad de extracción no acreditada"
    CONFLICT = "Conflicto"
    NOT_APPLICABLE = "Contrato no aplicable"


class SignConvention(StrEnum):
    SIGNED_COLUMN = "Importes con su signo en la columna documental"
    UNKNOWN = "Convención desconocida"


class TotalRelation(StrEnum):
    COLUMN_SUM = "Suma de filas monetarias de la columna"
    UNVERIFIED = "Participación en el total no acreditada"


class Unit(StrEnum):
    LOCAL_MONETARY = "Unidad monetaria común de la tabla; divisa no inferida"


@dataclass(frozen=True)
class BreakdownContract:
    contract_id: str
    version: str
    extractor_name: str
    extractor_revision: str
    justification: str
    signs: SignConvention = SignConvention.SIGNED_COLUMN
    unit: Unit = Unit.LOCAL_MONETARY
    sections: tuple[Section, ...] = (Section.EARNINGS, Section.DEDUCTIONS)
    excluded_columns: tuple[str, ...] = ("bases", "informacion")
    net_relation: bool = True
    total_relation: TotalRelation = TotalRelation.COLUMN_SUM

    def __post_init__(self) -> None:
        if not all(
            x.strip()
            for x in (
                self.contract_id,
                self.version,
                self.extractor_name,
                self.extractor_revision,
                self.justification,
            )
        ):
            raise ValueError("Reviewed identity, revision and justification required")


# These are reviewed CODE revisions, not corpus hashes or runtime hash discovery.
# Changing a parser/adapter requires explicit review and a new contract entry.
CONTRACTS = (
    BreakdownContract(
        "ineco-closed-table",
        "1",
        "InecoParser",
        "74dc6e38273d9af441d805ab6f4210435ee04478255a66edbf6bbfd8e59ba98c",
        "src/parsers/ineco_parser.py:_conceptos/_insurance_columns/_totals; "
        "bounded table, every row parsed or rejected, mirrored insurance; "
        "src/nomina_facts.py:adapt_nomina (all rows/source_position); docs/breakdown-contracts.md",
    ),
    BreakdownContract(
        "exceltic-closed-table",
        "1",
        "ExcelticParser",
        "fe24e63f0be084c868041dd92ff7cba6a52b0b11020a43a140e8775fe0ae374c",
        "src/parsers/exceltic_parser.py:parse/_concepts; bounded table, all rows "
        "or rejection, only PAGO POR TRANSFERENCIA omitted, mirrored aid; "
        "src/nomina_facts.py:adapt_nomina; docs/breakdown-contracts.md",
    ),
    BreakdownContract(
        "altran-closed-table",
        "1",
        "AltranParser",
        "f6954871c640f4b7d230a4a300beeaa4731647933c355ab1abc86dcf5704f55b",
        "src/parsers/altran_parser.py:parse_extracted/concept_column; bounded table, "
        "text/layout row equality, one monetary cell per row; "
        "src/nomina_facts.py:adapt_nomina; docs/breakdown-contracts.md",
        total_relation=TotalRelation.UNVERIFIED,
        net_relation=False,
    ),
)


@dataclass(frozen=True)
class CompletenessEvaluation:
    section: Section
    state: Completeness
    contract: BreakdownContract | None
    reasons: tuple[str, ...]
    participants: tuple[FactEvidence, ...] = ()
    excluded: tuple[str, ...] = ()
    target: FactEvidence | None = None


@dataclass(frozen=True)
class BreakdownDiagnosis:
    completeness: tuple[CompletenessEvaluation, ...]
    diagnostics: tuple[Diagnostic, ...]


def _money_text(text: str) -> ExactDecimal | None:
    # Printed signed decimal cells only. Never repair notation or round floats.
    if not re.fullmatch(r"-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2,4}-?", text):
        return None
    if text.startswith("-") and text.endswith("-"):
        return None
    normalized = text.replace(".", "").replace(",", ".")
    if normalized.endswith("-"):
        normalized = "-" + normalized[:-1]
    return ExactDecimal.from_text(normalized)


def _structural_reasons(e: ExtractionConcepts) -> tuple[str, ...]:
    facts = tuple(f.fact for f in e.facts)
    if (
        not e.content_hash
        or canonical_sha256({f.fact_key: f.value for f in facts}) != e.content_hash
    ):
        return ("extraction.content_unverified",)
    if any(not f.fact_key.startswith("nomina.") for f in facts):
        return ("extraction.scope_conflict",)
    try:
        reconstructed = project_extraction(
            e.document_id,
            e.version_id,
            e.extraction_id,
            facts,
            pages={f.fact.fact_id: f.pages for f in e.facts},
        )
    except ValueError:
        return ("extraction.scope_conflict",)
    if len({f.fact_key for f in facts}) != len(facts) or reconstructed.concepts != tuple(
        sorted(e.concepts, key=lambda c: c.occurrence)
    ):
        return ("extraction.scope_conflict",)
    processable = [f for f in facts if f.fact_key == "nomina.es_procesable"]
    if (
        len(processable) != 1
        or processable[0].value.state != ValueState.PRESENT
        or processable[0].value.value != "true"
    ):
        return ("extraction.not_processable",)
    if not e.concepts:
        return ("breakdown.absent",)
    expected = {
        "codigo",
        "concepto",
        "categoria",
        "columna",
        "importe",
        "importe_texto",
        "atraso",
        "porcentaje",
        "unidades",
        "precio",
        "base",
        "source_position",
    }
    positions = []
    for c in sorted(e.concepts, key=lambda row: row.occurrence):
        if (
            not c.occurrence.startswith("nomina.conceptos.")
            or {k for k, _ in c.attributes} != expected
        ):
            return ("extraction.row_projection_partial",)
        p = c.get("source_position")
        assert p is not None
        if p.fact.value.state != ValueState.PRESENT or not isinstance(
            p.fact.value.value, ExactDecimal
        ):
            return ("extraction.source_position_invalid",)
        positions.append(p.fact.value.value.to_decimal())
        column = c.get("columna")
        assert column is not None
        if column.fact.value.state != ValueState.PRESENT or column.fact.value.value not in (
            "devengos",
            "deducciones",
            "bases",
            "informacion",
        ):
            return ("row.accounting_unknown",)
    if sorted(positions) != list(range(len(e.concepts))):
        return ("extraction.source_position_invalid",)
    return ()


def evaluate_completeness(e: ExtractionConcepts) -> tuple[CompletenessEvaluation, ...]:
    """Evaluate each section, without computing any sum or authorizing a version."""
    contract = next(
        (
            c
            for c in CONTRACTS
            if (c.extractor_name, c.extractor_revision) == (e.extractor_name, e.extractor_revision)
        ),
        None,
    )
    structural = _structural_reasons(e) if contract else ()
    results = []
    for section, total in (
        (Section.EARNINGS, "total_devengado"),
        (Section.DEDUCTIONS, "total_deducir"),
    ):
        reasons = list(structural)
        state = Completeness.NOT_ACCREDITED
        parts: list[FactEvidence] = []
        excluded = []
        targets = [f for f in e.facts if f.fact.fact_key == "nomina." + total]
        target = targets[0] if len(targets) == 1 else None
        if contract is None:
            reasons = ["contract.unreviewed_extractor_revision"]
            state = Completeness.NOT_APPLICABLE
        elif structural:
            state = (
                Completeness.CONFLICT
                if "extraction.scope_conflict" in structural
                else Completeness.PARTIAL
                if any(r.startswith("extraction.") for r in structural)
                else Completeness.NOT_ACCREDITED
            )
        else:
            if contract.total_relation != TotalRelation.COLUMN_SUM:
                reasons.append("contract.total_scope_unverified")
            if contract.signs != SignConvention.SIGNED_COLUMN:
                reasons.append("contract.signs_unknown")
            for c in sorted(e.concepts, key=lambda row: row.occurrence):
                column = c.get("columna")
                assert column is not None
                if column.fact.value.value != section.value:
                    excluded.append(c.occurrence)
                    continue
                amount, text = c.get("importe"), c.get("importe_texto")
                assert amount is not None and text is not None
                parts.append(amount)
                if (
                    text.fact.value.state != ValueState.PRESENT
                    or not isinstance(text.fact.value.value, str)
                    or _money_text(text.fact.value.value) != amount.fact.value.value
                ):
                    reasons.append("row.printed_amount_unverified")
            if not parts:
                reasons.append("section.rows_absent")
            if target is None:
                reasons.append("section.total_missing_or_ambiguous")
            checked = (*parts, *((target,) if target else ()))
            if any(
                f.fact.value.state != ValueState.PRESENT
                or not isinstance(f.fact.value.value, ExactDecimal)
                for f in checked
            ):
                reasons.append("section.value_unusable")
            units = {f.fact.value.currency.code if f.fact.value.currency else None for f in checked}
            if len(units) > 1:
                reasons.append("section.incompatible_units")
            if not reasons:
                state = Completeness.ACCREDITED
        results.append(
            CompletenessEvaluation(
                section,
                state,
                contract,
                tuple(sorted(set(reasons))),
                tuple(parts),
                tuple(sorted(excluded)),
                target,
            )
        )
    return tuple(results)


def diagnose_breakdown(e: ExtractionConcepts) -> BreakdownDiagnosis:
    """Feed reviewed guarantees into B2a; never create a second arithmetic engine."""
    evaluations = evaluate_completeness(e)
    reviewed = evaluations[0].contract
    engine_contract = None
    if reviewed:
        engine_contract = ReconciliationContract(
            e.extractor_name,
            e.extractor_revision,
            f"{reviewed.contract_id}/{reviewed.version}: {reviewed.justification}",
            earnings_complete=evaluations[0].state == Completeness.ACCREDITED,
            deductions_complete=evaluations[1].state == Completeness.ACCREDITED,
            signed_columns=reviewed.signs == SignConvention.SIGNED_COLUMN,
            same_unit=True,
            net_relation=reviewed.net_relation,
        )
    return BreakdownDiagnosis(evaluations, reconcile(e, engine_contract))
