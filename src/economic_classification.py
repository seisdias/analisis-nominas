"""Non-persistent economic roles. Classification never grants additivity."""

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from src.canonical.values import ValueState
from src.document_concepts import ConceptOccurrence, ExtractionConcepts, FactEvidence
from src.economic_components import component_label


class Nature(StrEnum):
    EARNING = "Devengo"
    DEDUCTION = "Deducción"
    BASE = "Base económica"
    INFORMATION = "Información complementaria"
    UNKNOWN = "No determinado"


class Function(StrEnum):
    FIXED = "Retribución fija ordinaria: salario base identificado"
    COMPLEMENT = "Antigüedad o complemento identificado"
    INDEPENDENT_EXTRA = "Paga extraordinaria independiente"
    EXTRA = "Paga extraordinaria incluida"
    PRORATION = "Prorrata de extraordinarias"
    INFORMATIONAL_PRORATION = "Prorrata informativa de cotización"
    BONUS = "Bonus / variable / incentivo"
    BENEFITS = "Beneficios documentados"
    ADJUSTMENT = "Atraso o regularización"
    COMPENSATION = "Compensación, reembolso o ayuda"
    CONTRIBUTION = "Cotización del trabajador"
    TAX = "Retención fiscal"
    TOTAL = "Total documental"
    REFERENCE = "Referencia informativa"
    UNKNOWN = "No clasificable"


class Periodicity(StrEnum):
    RECURRENT = "Recurrente acreditado"
    ONE_OFF = "Puntual acreditado"
    UNKNOWN = "Desconocida"


class Relation(StrEnum):
    EARNING = "Componente de devengos; aditividad no acreditada"
    DEDUCTION = "Componente de deducciones; aditividad no acreditada"
    REFERENCE = "Base o referencia informativa; no añadir"
    TOTAL = "Total ya representado"
    UNKNOWN = "Relación desconocida"


class Knowledge(StrEnum):
    DOCUMENTED = "Documentado"
    CALCULATED = "Calculado"
    ESTIMATED = "Estimado"
    UNDETERMINABLE = "No determinable"


@dataclass(frozen=True)
class ClassifiedConcept:
    source: ConceptOccurrence
    nature: Nature
    function: Function
    relation: Relation
    arrears: bool | None
    periodicity: Periodicity = Periodicity.UNKNOWN
    contract: str = "economic-roles/b2a-v1"


@dataclass(frozen=True)
class ClassifiedReference:
    source: FactEvidence
    nature: Nature
    function: Function
    relation: Relation


@dataclass(frozen=True)
class Classification:
    extraction: ExtractionConcepts
    concepts: tuple[ClassifiedConcept, ...]
    references: tuple[ClassifiedReference, ...]
    issues: tuple[str, ...]


# Exact tuples beyond B1. Columns and arrears remain orthogonal, never inferred
# from an amount. Unlisted variants stay unknown even with a familiar category.
_ROLES: dict[tuple[str, str, str, str, str, str], Function] = {}


def _register(
    parser: str,
    code: str,
    label: str,
    category: str,
    role: Function,
    column: str = "devengos",
    arrears: str = "false",
) -> None:
    _ROLES[(parser, code, label, category, column, arrears)] = role


for code, label, category, role, column in (
    ("9001", "salario base", "salario_base", Function.FIXED, "devengos"),
    ("9002", "plus convenio", "plus_convenio", Function.COMPLEMENT, "devengos"),
    ("9003", "antiguedad", "antiguedad", Function.COMPLEMENT, "devengos"),
    ("9004", "comp.salarial", "complementos", Function.COMPLEMENT, "devengos"),
    ("9004", "comp. salarial", "complementos", Function.COMPLEMENT, "devengos"),
    ("90RG", "regulariz.salar", "regularizaciones", Function.ADJUSTMENT, "devengos"),
    ("/350", "trab.cont.comunes", "cotizacion_trabajador", Function.CONTRIBUTION, "deducciones"),
    ("T002", "dto base accidente", "cotizacion_trabajador", Function.CONTRIBUTION, "deducciones"),
    ("/401", "retencion irpf", "irpf", Function.TAX, "deducciones"),
    ("/402", "ingreso a cuenta irp", "ingreso_a_cuenta", Function.TAX, "deducciones"),
):
    _register("InecoParser", code, label, category, role, column)
for code, label, category, role in (
    ("9001", "salario base atra.", "atrasos", Function.FIXED),
    ("9002", "plus convenio atra.", "atrasos", Function.COMPLEMENT),
    ("9004", "comp.salarial atra.", "atrasos", Function.COMPLEMENT),
    ("9003", "antiguedad atra.", "antiguedad", Function.COMPLEMENT),
    ("9025", "pago de benefiatra.", "beneficios", Function.BENEFITS),
):
    _register("InecoParser", code, label, category, role, arrears="true")
for code, label, category, role, column in (
    ("1", "SALARIO BASE", "salario_base", Function.FIXED, "devengos"),
    ("1", "PLUS CONVENIO", "plus_convenio", Function.COMPLEMENT, "devengos"),
    ("1", "MEJORA VOLUNTARIA", "complemento_salarial", Function.COMPLEMENT, "devengos"),
    (
        "2",
        "DTO. CONT. COMUNES",
        "cotizacion_contingencias_comunes",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    (
        "2",
        "DTO.BASE ACCIDENTE",
        "cotizacion_desempleo_formacion_profesional",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    ("2", "RETENCION IRPF", "irpf", Function.TAX, "deducciones"),
):
    _register("ExcelticParser", code, label, category, role, column)
for code, column in (("1", "devengos"), ("2", "deducciones")):
    for label, category in (
        ("AYUDA COMIDA", "ayuda_comida"),
        ("AYUDA GUARDERIA", "ayuda_guarderia"),
    ):
        _register("ExcelticParser", code, label, category, Function.COMPENSATION, column)
for code, label, category, role, column in (
    ("R1A", "Salario Base", "salario_base", Function.FIXED, "devengos"),
    ("R1B", "Plus Convenio", "plus_convenio", Function.COMPLEMENT, "devengos"),
    ("R1R", "Mejora Voluntaria", "mejora_voluntaria", Function.COMPLEMENT, "devengos"),
    ("R1C", "Antigüedad", "antiguedad", Function.COMPLEMENT, "devengos"),
    (
        "705",
        "Cotización Contingencias Comunes",
        "cotizacion_contingencias_comunes",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    (
        "700",
        "Cotización Desempleo y FP",
        "cotizacion_desempleo_fp",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    ("F74", "Retención I.R.P.F.", "irpf_ordinario", Function.TAX, "deducciones"),
    ("FE4", "Retención I.R.P.F. Especie", "irpf_especie", Function.TAX, "deducciones"),
    ("R3L", "Ayuda ADSL", "ayuda_adsl", Function.COMPENSATION, "devengos"),
    ("R4L", "Ayuda ADSL", "ayuda_adsl", Function.COMPENSATION, "devengos"),
    ("R5S", "Ayuda Teletrabajo", "ayuda_teletrabajo", Function.COMPENSATION, "devengos"),
    ("R3A", "Compensa Comida", "compensacion_comida", Function.COMPENSATION, "deducciones"),
    ("R3C", "Compensa Guardería", "compensacion_guarderia", Function.COMPENSATION, "deducciones"),
    ("R3E", "Compensa Salud", "compensacion_salud", Function.COMPENSATION, "deducciones"),
    ("R3F", "Compensa Transporte", "compensacion_transporte", Function.COMPENSATION, "deducciones"),
):
    _register("AltranParser", code, label, category, role, column)
_register(
    "AltranParser",
    "R1X",
    "Parte Proporcional Pagas Extras",
    "paga_extra_incluida",
    Function.PRORATION,
    "deducciones",
    "true",
)
for code, label, category, role, column in (
    ("9001", "Salario Base Convenio", "salario_base", Function.FIXED, "devengos"),
    ("9003", "Plus Convenio", "plus_convenio", Function.COMPLEMENT, "devengos"),
    ("9004", "A Cuenta Convenio", "complemento_salarial", Function.COMPLEMENT, "devengos"),
    ("9039", "Antigüedad", "antiguedad", Function.COMPLEMENT, "devengos"),
    (
        "/350",
        "Trab.cont.comunes",
        "cotizacion_contingencias_comunes",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    ("/370", "Trab.desempleo", "cotizacion_desempleo", Function.CONTRIBUTION, "deducciones"),
    (
        "/380",
        "Trab.formac.profesional",
        "cotizacion_formacion",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    (
        "/SC0",
        "Trab. cuota solidaridad",
        "cotizacion_solidaridad",
        Function.CONTRIBUTION,
        "deducciones",
    ),
    ("/401", "Retención a cta. IRPF", "irpf", Function.TAX, "deducciones"),
):
    _register("alten-legacy-evidence", code, label, category, role, column)

_B1_ROLES = {
    "Extra de verano incluida": Function.EXTRA,
    "Extra de Navidad incluida": Function.EXTRA,
    "Prorratas de extras": Function.PRORATION,
    "Bonus / variable": Function.BONUS,
    "Ajustes de extras": Function.ADJUSTMENT,
}


def _text(c: ConceptOccurrence, field: str) -> str:
    e = c.get(field)
    return str(e.fact.value.value) if e and e.fact.value.state == ValueState.PRESENT else ""


def classify_extraction(e: ExtractionConcepts) -> Classification:
    concepts = []
    for c in sorted(e.concepts, key=lambda c: c.occurrence):
        column = _text(c, "columna")
        nature = {
            "devengos": Nature.EARNING,
            "deducciones": Nature.DEDUCTION,
            "bases": Nature.BASE,
            "informacion": Nature.INFORMATION,
        }.get(column, Nature.UNKNOWN)
        relation = {
            Nature.EARNING: Relation.EARNING,
            Nature.DEDUCTION: Relation.DEDUCTION,
            Nature.BASE: Relation.REFERENCE,
            Nature.INFORMATION: Relation.REFERENCE,
        }.get(nature, Relation.UNKNOWN)
        role = _B1_ROLES.get(component_label(e.extractor_name, c) or "", Function.UNKNOWN)
        if role == Function.UNKNOWN:
            role = _ROLES.get(
                (
                    e.extractor_name,
                    _text(c, "codigo"),
                    _text(c, "concepto"),
                    _text(c, "categoria"),
                    _text(c, "columna"),
                    _text(c, "atraso"),
                ),
                Function.UNKNOWN,
            )
        concepts.append(
            ClassifiedConcept(
                c, nature, role, relation, {"true": True, "false": False}.get(_text(c, "atraso"))
            )
        )
    references = []
    types = [f.fact.value for f in e.facts if f.fact.fact_key in ("nomina.tipo", "payload/tipo")]
    extra = bool(types) and all(
        v.state == ValueState.PRESENT and v.value == "PAGA_EXTRA" for v in types
    )
    for f in e.facts:
        key = f.fact.fact_key
        name = key.removeprefix("nomina.").removeprefix("payload/")
        if key not in ("nomina." + name, "payload/" + name):
            continue
        role = Function.UNKNOWN
        nature = Nature.INFORMATION
        relation = Relation.REFERENCE
        if name in ("total_devengado", "total_deducir", "liquido_percibir"):
            role = (
                Function.INDEPENDENT_EXTRA
                if name == "total_devengado" and extra
                else Function.TOTAL
            )
            relation = Relation.TOTAL
        elif name in (
            "base_ss_comunes",
            "base_at_ep",
            "base_irpf",
            "base_irpf_pie",
            "base_sujeta_retencion_irpf",
            "base_irpf_especie",
        ):
            nature = Nature.BASE
            role = Function.REFERENCE
        elif name == "prorrata_pagas_extra":
            if e.extractor_name in ("InecoParser", "ExcelticParser", "AltranParser"):
                role = Function.INFORMATIONAL_PRORATION
        elif name in ("irpf_porcentaje", "irpf_importe"):
            role = Function.TAX
        elif name in (
            "salario_base",
            "plus_convenio",
            "complementos",
            "descuento_seguridad_social",
            "otras_deducciones",
            "pror_otros",
        ):
            role = Function.REFERENCE
        else:
            continue
        references.append(ClassifiedReference(f, nature, role, relation))
    issues = []
    if not concepts:
        issues.append("Desglose de conceptos no disponible")
    if any(c.function == Function.UNKNOWN for c in concepts):
        issues.append("Hay conceptos sin correspondencia económica verificada")
    duplicates = Counter((_text(c.source, "codigo"), _text(c.source, "concepto")) for c in concepts)
    if any(n > 1 for n in duplicates.values()):
        issues.append(
            "Códigos o etiquetas repetidos: se conservan las ocurrencias, sin fusionarlas"
        )
    if any(
        (a := c.source.get("importe")) is None or a.fact.value.state != ValueState.PRESENT
        for c in concepts
    ):
        issues.append("Hay importes ausentes o no fiables")
    # Only these parsers explicitly derive these scalars from named ordinary rows.
    # Report mismatches without deduplicating, correcting or summing them.
    if e.extractor_name in ("InecoParser", "ExcelticParser", "AltranParser"):
        for field, categories in (
            ("salario_base", ("salario_base",)),
            ("plus_convenio", ("plus_convenio",)),
            ("complementos", ("complementos", "complemento_salarial", "mejora_voluntaria")),
        ):
            candidates = [
                c.source.get("importe")
                for c in concepts
                if c.function != Function.UNKNOWN
                and c.arrears is False
                and _text(c.source, "categoria") in categories
            ]
            scalars = [
                r.source
                for r in references
                if r.source.fact.fact_key in ("nomina." + field, "payload/" + field)
            ]
            if len(candidates) == len(scalars) == 1 and candidates[0] is not None:
                row_value, scalar_value = candidates[0].fact.value, scalars[0].fact.value
                if (
                    row_value.state == scalar_value.state == ValueState.PRESENT
                    and row_value.currency == scalar_value.currency
                    and row_value.value != scalar_value.value
                ):
                    issues.append(
                        "Posible discrepancia entre "
                        + field
                        + " y su fila; sin corrección automática"
                    )
    return Classification(e, tuple(concepts), tuple(references), tuple(issues))
