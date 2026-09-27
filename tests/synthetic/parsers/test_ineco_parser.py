"""Synthetic layouts: no private documents, employee data or audited amounts."""

import json
from dataclasses import replace

import pytest

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.ineco_parser import InecoParser
from src.parsers.parser_factory import ParserFactory
from src.services.database_service import DatabaseService

OLD = """Empresa
Ing.y Econ.del Transporte 00000000000 A28220168
Periodo de liquidación Número trabajador Dirección de área
01.10.2099 31.10.2099 DEMO
Concepto Unidades Precio Devengos Deducciones
9001 Salario Base 1.500,00
9002 Plus Convenio 200,00
9004 Comp.Salarial 100,00
/401 Retención IRPF 15,00 270,00
COTIZACIÓN SEGURIDAD SOCIAL
Base Accidentes Total Devengos Total Deducciones
Remuneración
1.800,00 2.000,00 1.800,00 400,00
Total:
Prorratas pagas B.C. Comunes
200,00
extras :
Total Base: 2.000,00
2.000,00 Líquido a percibir: 1.400,00
ATRA Base Cotiz:
"""
NEW = """Empresa: Ing.y Econ.del Transporte CCC: 00000000000 CIF: A28220168
Periodo Liquidación Trabajador Dirección de Área
01.10.2099 31.10.2099 DEMO
Concepto Unidades Precio Devengos Deducciones
9001 Salario Base 1.500,00
9002 Plus Convenio 200,00
9004 Comp.Salarial 100,00
/401 Retención IRPF 15,00 210,00
Cotizacion Seg. Social B.C.Comunes Base D IRPF Devengos Deducciones
Remu. Cotizables: 1.600,00 2.000,00 1.700,00 1.800,00 400,00
Prorrata: 200,00
Total Base: 2.000,00 Base AT y EP B.Esp. IRPF Liquido a Percibir
ATRA Base Cotiz: 25,00 1.400,00
2.000,00 0,00
"""


@pytest.mark.parametrize("text,base,tax", [(OLD, None, 270.0), (NEW, 1700.0, 210.0)],
                         ids=["old", "2015"])
def test_fundamentals(text: str, base: float | None, tax: float) -> None:
    doc = InecoParser().parse(text, filename="irrelevant_190001.pdf")
    assert (doc.empresa, doc.cif) == ("Ing.y Econ.del Transporte", "A28220168")
    assert (doc.fecha_inicio, doc.fecha_fin) == ("2099-10-01", "2099-10-31")
    assert (doc.anio, doc.mes, doc.periodo) == (2099, 10, "2099-10")
    assert (doc.total_devengado, doc.total_deducir, doc.liquido_percibir) == (1800, 400, 1400)
    assert (doc.irpf_porcentaje, doc.irpf_importe) == (15, tax)
    assert doc.base_irpf == base
    assert doc.tipo == TipoDocumento.NOMINA_ORDINARIA
    assert doc.salario_base == 1500
    # No residual arithmetic masquerading as extracted deductions.
    assert doc.descuento_seguridad_social is None
    assert doc.otras_deducciones is None


def test_included_extra_is_ordinary_and_preserves_legacy_storage_id() -> None:
    doc = InecoParser().parse(OLD.replace("9001", "9000 PAGA EXTRA 100,00\n9001"))
    assert doc.tipo == TipoDocumento.NOMINA_ORDINARIA
    assert doc.id == "2099-10-INECO-EXTRA"  # Storage compatibility, not classification.


def test_full_month_reingestion_updates_legacy_row() -> None:
    service = DatabaseService(":memory:")
    service.init_db()
    doc = InecoParser().parse(OLD)
    service.guardar_documento(replace(doc, id="2099-10-INECO", total_devengado=1))
    service.guardar_documento(doc)
    rows = service.obtener_todos()
    assert len(rows) == 1 and rows[0]["total_devengado"] == 1800


def test_partial_periods_have_distinct_stable_ids_and_survive_storage() -> None:
    first = OLD.replace("31.10.2099", "09.10.2099")
    second = OLD.replace("01.10.2099", "10.10.2099")
    docs = [InecoParser().parse(text) for text in (first, second)]
    assert docs[0].id != docs[1].id
    assert docs[0].fecha_fin == "2099-10-09"
    assert docs[1].fecha_inicio == "2099-10-10"
    assert [doc.id for doc in docs] == [InecoParser().parse(t, "other.pdf").id
                                      for t in (first, second)]
    service = DatabaseService(":memory:")
    service.init_db()
    for doc in docs * 2:
        service.guardar_documento(doc)
    assert len(service.obtener_todos()) == 2
    for row in service.obtener_todos():
        restored = Nomina.from_dict(json.loads(row["payload"]))
        assert restored.fecha_inicio in {"2099-10-01", "2099-10-10"}
        assert restored.base_irpf is None


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_absent_irpf_is_not_zero(text: str) -> None:
    text = "\n".join(line for line in text.splitlines() if not line.startswith("/401"))
    doc = InecoParser().parse(text)
    assert doc.irpf_porcentaje is None and doc.irpf_importe is None
    assert Nomina.from_dict(json.loads(json.dumps(doc.to_dict()))).irpf_importe is None


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_printed_zero_net_is_preserved(text: str) -> None:
    doc = InecoParser().parse(text.replace("1.400,00", "0,00").replace("1.800,00 400,00", "1.800,00 1.800,00"))
    assert doc.liquido_percibir == 0
    assert doc.total_deducir == 1800


def test_printed_zero_irpf_is_distinct_from_absence() -> None:
    doc = InecoParser().parse(OLD.replace("15,00 270,00", "0,00 0,00"))
    assert (doc.irpf_porcentaje, doc.irpf_importe) == (0, 0)


def test_irpf_is_not_recomputed() -> None:
    doc = InecoParser().parse(NEW.replace("15,00 210,00", "15,00 75,00-"))
    assert doc.irpf_importe == -75
    assert doc.base_irpf == 1700


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
@pytest.mark.parametrize("replacement", ["", "Wrong Company", "A00000000"])
def test_identity_is_required(text: str, replacement: str) -> None:
    if replacement == "A00000000":
        text = text.replace("A28220168", replacement)
    else:
        text = text.replace("Ing.y Econ.del Transporte", replacement)
    with pytest.raises(ValueError, match="identity"):
        InecoParser().parse(text, "ineco.pdf")


@pytest.mark.parametrize("replacement", ["", "31.02.2099 31.10.2099", "31.10.2099 01.10.2099",
                                          "01.09.2099 31.10.2099"])
def test_invalid_or_missing_period(replacement: str) -> None:
    with pytest.raises(ValueError, match="period"):
        InecoParser().parse(OLD.replace("01.10.2099 31.10.2099", replacement))


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
@pytest.mark.parametrize("amount", ["1.10,00", "150,00INVALID", "....", "NaN"])
def test_invalid_total_is_rejected(text: str, amount: str) -> None:
    with pytest.raises(ValueError, match="total"):
        InecoParser().parse(text.replace("1.800,00 400,00", f"{amount} 400,00"))


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_missing_required_totals(text: str) -> None:
    with pytest.raises(ValueError, match="total"):
        InecoParser().parse(text.replace("1.800,00 400,00", "1.800,00"))


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_missing_net_cannot_be_taken_from_next_base_row(text: str) -> None:
    with pytest.raises(ValueError, match="net|total|balance"):
        InecoParser().parse(text.replace("1.400,00", ""))


def test_bad_irpf_is_not_treated_as_absent() -> None:
    with pytest.raises(ValueError, match="IRPF"):
        InecoParser().parse(OLD.replace("15,00 270,00", "15,00 INVALID"))


def test_missing_printed_base_is_not_replaced_with_gross() -> None:
    with pytest.raises(ValueError, match="total|base"):
        InecoParser().parse(NEW.replace("1.700,00 ", ""))


def test_common_balance_validation_still_rejects_inconsistent_document() -> None:
    with pytest.raises(ValueError, match="balance"):
        InecoParser().parse(OLD.replace("1.400,00", "1.300,00"))


def test_whitespace_variation_preserves_rows() -> None:
    doc = InecoParser().parse(NEW.replace(" ", "\t  ").replace("\n", "\r\n\n"))
    assert doc.total_devengado == 1800


def test_partial_with_liquidation_concepts_is_still_ordinary() -> None:
    text = NEW.replace("31.10.2099", "10.10.2099") + "\n9010 Liquidacion vacaciones 80,00"
    assert InecoParser().parse(text).tipo == TipoDocumento.NOMINA_ORDINARIA


def test_factory_identifies_company_without_filename() -> None:
    assert isinstance(ParserFactory().obtener_parser(OLD), InecoParser)


def test_basic_concepts_with_separate_arrears_do_not_block_fundamentals() -> None:
    text = OLD.replace("9001 Salario Base", "9001 Salario Base ATRA. 80,00-\n9001 Salario Base")
    doc = InecoParser().parse(text)
    assert doc.salario_base == 1500  # Arrears breakdown belongs to phase 2.
    assert doc.total_devengado == 1800


def test_modern_remuneration_label_without_internal_space() -> None:
    doc = InecoParser().parse(NEW.replace("Remu. Cotizables:", "Remu.Cotizables:"))
    assert doc.base_irpf == 1700
    assert doc.liquido_percibir == 1400


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_zero_net_is_never_replaced_to_make_the_balance_pass(text: str) -> None:
    with pytest.raises(ValueError, match="balance"):
        InecoParser().parse(text.replace("1.400,00", "0,00"))


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_explicit_common_base_and_proration(text: str) -> None:
    doc = InecoParser().parse(text.replace("Total Base: 2.000,00", "Total Base: 1.900,00"))
    assert doc.base_ss_comunes == 2000
    assert doc.prorrata_pagas_extra == 200


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_absent_proration_is_not_zero(text: str) -> None:
    text = text.replace("Prorrata: 200,00\n", "").replace("Prorratas pagas B.C. Comunes\n200,00", "B.C. Comunes")
    doc = InecoParser().parse(text)
    assert doc.prorrata_pagas_extra is None
    assert doc.base_ss_comunes == 2000


def test_absent_common_base_old_template() -> None:
    doc = InecoParser().parse(OLD.replace("2.000,00 Líquido", "Líquido"))
    assert doc.base_ss_comunes is None


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_printed_zero_common_base_and_proration(text: str) -> None:
    text = text.replace("2.000,00", "0,00").replace("200,00", "0,00")
    doc = InecoParser().parse(text)
    assert doc.base_ss_comunes == 0 and doc.prorrata_pagas_extra == 0


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_irpf_outside_concept_table_is_not_payroll_irpf(text: str) -> None:
    text = "\n".join(row for row in text.splitlines() if not row.startswith("/401"))
    doc = InecoParser().parse(text + "\n/401 Retención IRPF 12,00 50,00")
    assert doc.irpf_porcentaje is None and doc.irpf_importe is None


def test_modern_table_without_common_base_column() -> None:
    text = NEW.replace(" B.C.Comunes", "").replace("1.600,00 2.000,00 1.700,00", "1.600,00 1.700,00")
    doc = InecoParser().parse(text)
    assert doc.base_ss_comunes is None
    assert doc.base_irpf == 1700 and doc.total_devengado == 1800


@pytest.mark.parametrize("text", [OLD, NEW], ids=["old", "2015"])
def test_invalid_proration_rejected(text: str) -> None:
    text = text.replace("\n200,00\nextras", "\n1.10,00\nextras").replace("Prorrata: 200,00", "Prorrata: 1.10,00")
    with pytest.raises(ValueError, match="proration"):
        InecoParser().parse(text)


def test_proration_outside_payroll_summary_is_not_used() -> None:
    text = NEW.replace("Prorrata: 200,00\n", "") + "\nProrrata: 75,00"
    assert InecoParser().parse(text).prorrata_pagas_extra is None
