"""Evidence checklist, not a new salary engine or a production accreditation rule."""

from calendar import monthrange
from dataclasses import dataclass

from src.canonical.serialization import canonical_sha256
from src.canonical.values import ValueState
from src.document_concepts import ExtractionConcepts, FactEvidence
from src.salary_reconciliation import Status
from src.salary_reconstruction import (
    AnnualContract,
    Bucket,
    Coverage,
    FixedContract,
    Indicator,
    PaymentContract,
    PaymentMode,
    Reconstruction,
    identified_ordinary,
    reconstruct,
    scope_for,
)


@dataclass(frozen=True)
class SalaryRequirement:
    key: str
    label: str
    satisfied: bool
    reason: str
    needed: str
    facts: tuple[FactEvidence, ...] = ()


@dataclass(frozen=True)
class SalaryEvidence:
    reconstruction: Reconstruction
    ordinary: Indicator
    requirements: tuple[SalaryRequirement, ...]
    unresolved: tuple[str, ...]


def describe_salary(
    e: ExtractionConcepts, r: Reconstruction, ordinary: Indicator
) -> SalaryEvidence:
    """Explain an existing scenario without selecting versions or granting guarantees.

    Like reconstruction contracts, the scenario is internal, not user-supplied.
    Reviewed fixed/payment/annual guarantees remain entirely in B2b.2.
    """
    if r.scope != scope_for(e):
        raise ValueError("Salary evidence requires the same extraction scope")
    dates = tuple(
        f for f in e.facts if f.fact.fact_key in ("nomina.fecha_inicio", "nomina.fecha_fin")
    )
    present = {
        f.fact.fact_key: f.fact.value.value
        for f in dates
        if f.fact.value.state == ValueState.PRESENT
    }
    whole = False
    intact = e.content_hash == canonical_sha256({f.fact.fact_key: f.fact.value for f in e.facts})
    if intact and r.period and len(dates) == len(present) == 2:
        y, m = r.period
        whole = (
            present.get("nomina.fecha_inicio") == f"{y:04d}-{m:02d}-01"
            and present.get("nomina.fecha_fin") == f"{y:04d}-{m:02d}-{monthrange(y, m)[1]:02d}"
        )
    candidates = tuple(
        f
        for p in r.parts
        if p.bucket in (Bucket.FIXED_CANDIDATE, Bucket.FIXED)
        if (f := p.source.source.get("importe")) is not None
    )
    unresolved = tuple(
        p.source.source.occurrence
        for p in r.parts
        if p.bucket == Bucket.UNKNOWN or p.amount is None
    )
    fixed = r.fixed.amount is not None
    complete = fixed and r.fixed.coverage == Coverage.COMPLETE
    salary_month = fixed and any(isinstance(c, FixedContract) and c.full_month for c in r.contracts)
    mode = r.payment_mode not in (PaymentMode.UNKNOWN, PaymentMode.DECLARED)
    annual = r.annual.amount is not None and r.annual.coverage == Coverage.COMPLETE
    extra_facts = tuple(
        f
        for p in r.parts
        if p.bucket in (Bucket.EXTRA, Bucket.PRORATION)
        if (f := p.source.source.get("importe")) is not None
    )
    if e.extractor_name == "ExcelticParser":
        recurrence = "Este formato identifica salario base, plus convenio y mejora voluntaria; falta acreditar la naturaleza fija de los complementos presentes."
        structure = "P.P.EXTRA, cuando consta en devengos, acredita esa prorrata, no doce mensualidades ni todas las extras anuales."
        agreement = "Acuerdo de prorrateo y contrato o convenio aplicable: pagas cubiertas, composición, vigencia y mensualidades."
    elif e.extractor_name == "InecoParser":
        recurrence = "Salario base, plus convenio, antigüedad y complemento salarial pueden identificarse; su presencia no acredita la recurrencia de cada complemento."
        structure = "Las extras de verano/Navidad, cuando constan, acreditan partidas individuales; falta su composición, devengo y multiplicidad anual."
        agreement = "Contrato o convenio aplicable y acuerdo salarial vigente: composición de cada extra y periodo de devengo."
    else:
        recurrence = (
            "Las partidas identificadas no acreditan por sí solas recurrencia ni cobertura fija."
        )
        structure = "No hay contrato revisado de modalidad anual aplicable a esta extracción."
        agreement = "Acuerdo retributivo aplicable que documente periodicidad, composición de extras y vigencia."
    requirements = (
        SalaryRequirement(
            "calendar",
            "Mes civil documental",
            whole,
            "Intervalo explícito del primer al último día; no prueba jornada ni mensualidad salarial íntegra."
            if whole
            else "El intervalo no acredita un mes civil completo o no está disponible.",
            "Intervalo documental íntegro; para salario mensual, condiciones de jornada e incidencias."
            if not whole
            else "",
            dates,
        ),
        SalaryRequirement(
            "accounting",
            "Devengos conciliados",
            r.earnings.status == Status.RECONCILED,
            r.earnings.status.value + ". " + r.earnings.reason,
            "Desglose completo, valores fiables y total compatible de esta extracción."
            if r.earnings.status != Status.RECONCILED
            else "",
            r.earnings.participants,
        ),
        SalaryRequirement(
            "recurrence",
            "Naturaleza fija de los componentes",
            fixed,
            r.fixed.reason if fixed else recurrence,
            "Acuerdo salarial o cláusula documental que identifique los componentes fijos, su recurrencia y vigencia."
            if not fixed
            else "",
            candidates,
        ),
        SalaryRequirement(
            "fixed",
            "Cobertura del fijo ordinario",
            complete,
            r.fixed.reason
            if complete
            else (
                "No hay cobertura contractual del fijo. "
                + ("Existen partidas sin clasificar o sin importe fiable. " if unresolved else "")
                + "Conciliar todos los devengos no acredita que los candidatos cubran todo el fijo."
            ),
            "Composición íntegra del fijo aplicable al periodo y acreditación de jornada/incidencias; no basta repetir importes."
            if not complete
            else "",
            candidates,
        ),
        SalaryRequirement(
            "salary_month",
            "Mensualidad salarial íntegra",
            salary_month,
            "Contrato retributivo revisado de mensualidad íntegra."
            if salary_month
            else "Las fechas de liquidación no acreditan por sí solas jornada, incidencias ni una mensualidad salarial íntegra.",
            "Acuerdo de jornada y cobertura salarial del periodo, con tratamiento de altas, bajas y ausencias."
            if not salary_month
            else "",
            dates,
        ),
        SalaryRequirement(
            "payment",
            "Modalidad de pagas",
            mode,
            r.payment_mode.value if mode else structure,
            agreement if not mode else "",
            extra_facts,
        ),
        SalaryRequirement(
            "annual",
            "Equivalencia mensual/anual",
            annual,
            r.annual.reason
            if annual
            else "Faltan cobertura fija completa, mensualidad íntegra y composición anual acreditada. No se aplica ×12 ni ×14.",
            agreement + " Mensualidad íntegra y cobertura de todos los componentes fijos."
            if not annual
            else "",
            r.annual.participants,
        ),
    )
    return SalaryEvidence(r, ordinary, requirements, unresolved)


def assess_salary(
    e: ExtractionConcepts,
    fixed: FixedContract | None = None,
    payment: PaymentContract | None = None,
    annual: AnnualContract | None = None,
) -> SalaryEvidence:
    return describe_salary(e, reconstruct(e, fixed, payment, annual), identified_ordinary(e))


def evidence_rows(report: SalaryEvidence) -> list[dict[str, str]]:
    return [
        {
            "Requisito": q.label,
            "Estado": "Acreditado en su ámbito" if q.satisfied else "Pendiente de acreditar",
            "Evidencia y límite": q.reason,
            "Qué falta": q.needed or "Requisito satisfecho; no amplía otras garantías",
        }
        for q in report.requirements
    ]
