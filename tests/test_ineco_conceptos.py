"""Entirely synthetic economic rows; amounts and dates are fictional."""

import json

import pytest

from src.models.nomina import Nomina
from src.parsers.ineco_parser import InecoParser
from src.services.database_service import DatabaseService
from tests.test_ineco_parser import NEW, OLD


def payroll(rows: str, template: str = OLD) -> str:
    return template.replace("/401", rows + "\n/401")


@pytest.mark.parametrize("row,category,amount,arrears", [
    ("9003 Antigüedad 50,00", "antiguedad", 50, False),
    ("9033 Paga extra Navi 400,00", "paga_extra_incluida", 400, False),
    ("9025 Pago de BenefiATRA. 80,00", "beneficios", 80, True),
    ("9002 Plus Convenio ATRA. 25,00-", "atrasos", -25, True),
    ("9003 Antigüedad ATRA. 10,00", "antiguedad", 10, True),
    ("90RG Regulariz.salar 45,00", "regularizaciones", 45, False),
    ("90RG Regulariz.salar 45,00-", "regularizaciones", -45, False),
    ("9RPE R. PExt Dic 2099 70,00-", "regularizaciones", -70, False),
    ("PA40 Prestac.oblig.E 2,00 90,00", "prestaciones", 90, False),
    ("PC10 Complementos ITATRA. 30,00-", "prestaciones", -30, True),
    ("9102 Liquidación vac 2,00 40,00 80,00", "vacaciones", 80, False),
])
def test_economic_categories(row: str, category: str, amount: float, arrears: bool) -> None:
    doc = InecoParser().parse(payroll(row))
    concept = next(c for c in doc.conceptos if c.codigo == row.split()[0]
                   and c.categoria == category)
    assert (concept.importe, concept.atraso, concept.columna) == (amount, arrears, "devengos")
    assert doc.tipo.value == "NOMINA_ORDINARIA"
    assert doc.prorrata_pagas_extra == 200  # Printed proration, not the included extra.


def test_repeated_codes_and_complements_are_preserved_and_aggregated() -> None:
    doc = InecoParser().parse(payroll("9004 Comp. Salarial 40,00\n9004 Comp.Salarial 10,00-"))
    rows = [c for c in doc.conceptos if c.codigo == "9004"]
    assert [c.importe for c in rows] == [100, 40, -10]
    assert doc.complementos == 130
    assert doc.salario_base == 1500 and doc.plus_convenio == 200


@pytest.mark.parametrize("template", [OLD, NEW], ids=["old", "2015"])
def test_insurance_columns_and_withholding_payment(template: str) -> None:
    text = template.replace("9002", "9B09 Seguro de Vida ATRA. 4.56\n9002")
    text = payroll("9B09 Seguro de Vida 4,56\n/402 Ingreso a cuenta IRP 0,50", text)
    doc = InecoParser().parse(text)
    insurance = [c for c in doc.conceptos if c.codigo == "9B09"]
    assert [(c.columna, c.importe) for c in insurance] == [("devengos", 4.56), ("deducciones", 4.56)]
    assert insurance[0].importe_texto == "4.56"
    payment = next(c for c in doc.conceptos if c.codigo == "/402")
    assert (payment.categoria, payment.columna, payment.importe) == ("ingreso_a_cuenta", "deducciones", .5)
    assert doc.otras_deducciones is None


def test_explicit_contributions_repeated_and_employer_section_excluded() -> None:
    text = payroll("T002 Dto Base Accidente 1,00\nT002 Dto Base Accidente 1,50 20,00\n"
                   "/350 Trab.cont.comunes 4,70 60,00", NEW)
    text += "\nDeterminación aportación empresarial\n/350 Trab.cont.comunes 23,60 500,00"
    doc = InecoParser().parse(text)
    ss = [c for c in doc.conceptos if c.categoria == "cotizacion_trabajador"]
    assert [(c.importe, c.porcentaje) for c in ss] == [(1, None), (20, 1.5), (60, 4.7)]
    assert all(c.columna == "deducciones" for c in ss)
    assert doc.descuento_seguridad_social is None


def test_partial_vacations_units_and_price_are_printed_not_derived() -> None:
    text = payroll("9102 Liquidación vac 2,00 40,00 79,99", NEW).replace("31.10.2099", "10.10.2099")
    doc = InecoParser().parse(text)
    row = next(c for c in doc.conceptos if c.codigo == "9102")
    assert (row.unidades, row.precio, row.importe) == (2, 40, 79.99)
    assert doc.tipo.value == "NOMINA_ORDINARIA"


def test_concepts_roundtrip_existing_json_storage() -> None:
    doc = InecoParser().parse(payroll("9003 Antigüedad 25,00"))
    service = DatabaseService(":memory:")
    service.init_db()
    service.guardar_documento(doc)
    payload = json.loads(service.obtener_todos()[0]["payload"])
    assert Nomina.from_dict(payload).conceptos == doc.conceptos
    del payload["conceptos"]
    assert Nomina.from_dict(payload).conceptos == []  # Legacy payloads remain readable.


@pytest.mark.parametrize("amount", ["1.10,00", "40,00INVALID", ".... 40,00", "NaN", "-40,00-"])
def test_bad_economic_amount_rejected(amount: str) -> None:
    with pytest.raises(ValueError):
        InecoParser().parse(payroll(f"9003 Antigüedad {amount}"))


def test_decimal_point_exception_is_not_global() -> None:
    with pytest.raises(ValueError):
        InecoParser().parse(payroll("9003 Antigüedad 4.56"))


def test_unpaired_insurance_column_is_ambiguous() -> None:
    with pytest.raises(ValueError, match="insurance"):
        InecoParser().parse(payroll("9B09 Seguro de Vida 4,56"))


def test_arrears_marker_cannot_repair_a_malformed_amount() -> None:
    with pytest.raises(ValueError):
        InecoParser().parse(payroll("9003 Antigüedad 4,ATRA.56"))
