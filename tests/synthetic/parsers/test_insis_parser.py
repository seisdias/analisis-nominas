"""Entirely synthetic INSIS4 structures; no private payroll fixtures."""

import pytest

from src.models.documento_laboral import TipoDocumento
from src.parsers.insis_parser import InsisParser, _parse_money


@pytest.fixture
def ordinary() -> str:
    return """INTELIGENCIA SISTEMATICA 4 SL CIF B84225283
Trabajador: PERSONA FICTICIA
Período de liquidación: 1 DE JULIO A 31 DE JULIO DE 2099
I.DEVENGOS TOTALES
Salario Base 1.000,00
Horas extraordinarias
Gratificaciones extr.
P.CONVENIO 100,00
INCENTIVOS 50,00
TRANSPORTE 25,00
CTA.CONVEN 15,00
ATRASOS 10,00
A . T O T A L D E V E N G A D O ........1...2..0..0,00
II.DEDUCCIONES
TOTAL APORTACIONES .... 60,00
2. Impuesto sobre la renta .... 10,00 120,00
3. Anticipos ................................
4. Valor de los productos recibidos en especie
5. Otras deducciones
B. TOTAL A DEDUCIR .... 180,00
LIQUIDO TOTAL A PERCIBIR [A-B] 169714 PTA 1.020,00
31 de J U L I O de 2099
1. Base de cotización por contingencias comunes
Prorrata pagas extraordinarias .... 150,00
TOTAL .... 1.350,00
4. Base s uj et a a re te nc ió n del I.R.P.F. .... 1.100,00
"""


@pytest.fixture
def extra() -> str:
    return """INTELIGENCIA SISTEMATICA 4 SL CIF B84225283
Período de liquidación: PAGA EXTRA Total días
I.DEVENGOS TOTALES
Salario Base
Horas extraordinarias
500,00
Gratificaciones extr.
Salario en especie
A. TOTAL DEVENGADO .... 500,00
II.DEDUCCIONES
TOTAL APORTACIONES ................................
2. Impuesto sobre la renta .... 10,00 50,00
3. Anticipos ................................
4. Valor de los productos recibidos en especie
B. TOTAL A DEDUCIR .... 50,00
LIQUIDO TOTAL A PERCIBIR [A-B] 74874 PTA 450,00
15 de J U L I O de 2099
1. Base de cotización por contingencias comunes
Prorrata pagas extraordinarias ................................
TOTAL ................................
4. Base sujeta a retención del I.R.P.F. .... 500,00
"""


@pytest.fixture
def modern(ordinary: str) -> str:
    return (ordinary.replace("P.CONVENIO", "PLUS CONVENIO")
            .replace("INCENTIVOS", "GRAT.VOL.ABS.")
            .replace("CTA.CONVEN", "A CTA.CONV")
            .replace("TRANSPORTE", "P.TRANSPORTE")
            .replace("........1...2..0..0,00", "1.200,00")
            .replace("TOTAL APORTACIONES .... 60,00", "1.TOTAL APORTACIONES 60,00")
            .replace("Impuesto sobre la renta .... 10,00", "I.R.P.F. 1 0 , 0 0 %")
            .replace("A DEDUCIR ....", "A DEDUCIR (1+2+3+4+5+6+7)")
            .replace("169714 PTA", "EUROS")
            .replace("TOTAL .... 1.350,00\n4.", "TOTAL 1.350,00 4."))


@pytest.mark.parametrize(("raw", "expected"), [
    ("1.234,56", 1234.56), ("1234,56", 1234.56), ("0,00", 0.0), ("-12,34", -12.34),
])
def test_spanish_money(raw: str, expected: float) -> None:
    assert _parse_money(raw) == expected


@pytest.mark.parametrize("raw", ["", "4.", "1.23,45", "1,234.56", "12,3", "NaN", "1,00\n4."])
def test_invalid_money(raw: str) -> None:
    with pytest.raises(ValueError, match="amount"):
        _parse_money(raw)


@pytest.mark.parametrize("fixture", ["ordinary", "modern"])
def test_ordinary_formats(fixture: str, request: pytest.FixtureRequest) -> None:
    doc = InsisParser().parse(request.getfixturevalue(fixture), "190001_extra.pdf")
    assert (doc.anio, doc.mes, doc.tipo) == (2099, 7, TipoDocumento.NOMINA_ORDINARIA)
    assert doc.id == "2099-07-INSIS"
    assert (doc.total_devengado, doc.total_deducir, doc.liquido_percibir) == (1200, 180, 1020)
    assert (doc.salario_base, doc.plus_convenio, doc.complementos) == (1000, 100, 100)
    assert (doc.irpf_porcentaje, doc.irpf_importe) == (10, 120)
    assert doc.base_irpf == 1100  # Explicit, deliberately different from gross.
    assert doc.base_ss_comunes == 1350
    assert doc.otras_deducciones == 0  # Never the next section's "4.".
    assert doc.prorrata_pagas_extra == 150


def test_explicit_advance(ordinary: str) -> None:
    text = ordinary.replace("Anticipos ................................", "Anticipos .... 20,00")
    text = text.replace("180,00", "200,00").replace("1.020,00", "1.000,00")
    assert InsisParser().parse(text).otras_deducciones == 20


def test_extra_and_distinct_ids(ordinary: str, extra: str) -> None:
    parser = InsisParser()
    doc = parser.parse(extra, "190001_ordinary.pdf")
    assert doc.tipo == TipoDocumento.PAGA_EXTRA
    assert doc.id == "2099-07-INSIS-EXTRA"
    assert doc.id != parser.parse(ordinary).id
    assert (doc.salario_base, doc.complementos) == (0, 500)
    assert (doc.total_devengado, doc.total_deducir, doc.liquido_percibir) == (500, 50, 450)
    assert doc.descuento_seguridad_social == 0


def test_irpf_credit_is_not_recalculated(ordinary: str) -> None:
    text = ordinary.replace("10,00 120,00", "10,00 80,00(Abono IRPF 40,00)")
    text = text.replace("180,00", "140,00").replace("1.020,00", "1.060,00")
    assert InsisParser().parse(text).irpf_importe == 80


@pytest.mark.parametrize("label", ["A . T O T A L D E V E N G A D O", "B. TOTAL A DEDUCIR",
                                      "LIQUIDO TOTAL A PERCIBIR", "4. Base s uj et a"])
def test_missing_required_field(ordinary: str, label: str) -> None:
    text = "\n".join(line for line in ordinary.splitlines() if not line.startswith(label))
    with pytest.raises(ValueError, match="Missing"):
        InsisParser().parse(text)


@pytest.mark.parametrize("replacement", ["invalid", "1.23,45", " "])
def test_invalid_total(ordinary: str, replacement: str) -> None:
    text = ordinary.replace("........1...2..0..0,00", replacement)
    with pytest.raises(ValueError, match="amount|Missing"):
        InsisParser().parse(text)


def test_zero_total_is_not_replaced(ordinary: str) -> None:
    text = ordinary.replace("........1...2..0..0,00", "0,00")
    with pytest.raises(ValueError, match="balance"):
        InsisParser().parse(text)


def test_wrong_company(ordinary: str) -> None:
    text = ordinary.replace("INTELIGENCIA SISTEMATICA 4 SL CIF B84225283", "EMPRESA FICTICIA")
    with pytest.raises(ValueError, match="INSIS4"):
        InsisParser().parse(text)


def test_balance_rejected(ordinary: str) -> None:
    with pytest.raises(ValueError, match="balance"):
        InsisParser().parse(ordinary.replace("1.020,00", "1.021,00"))


def test_extra_missing_date(extra: str) -> None:
    with pytest.raises(ValueError, match="period"):
        InsisParser().parse(extra.replace("15 de J U L I O de 2099", ""), "209907.pdf")


def test_missing_irpf_is_not_zero(ordinary: str) -> None:
    with pytest.raises(ValueError, match="IRPF"):
        InsisParser().parse(ordinary.replace("2. Impuesto sobre la renta .... 10,00 120,00", ""))


def test_extra_date_beside_signature_label(extra: str) -> None:
    text = extra.replace("15 de J U L I O de 2099", "Firma y sello de la empresa MADRID, 15 de J U L I O de 2099")
    assert InsisParser().parse(text).periodo == "2099-07"


def test_malformed_base_with_leaders_is_rejected(ordinary: str) -> None:
    text = ordinary.replace(".... 1.100,00", ".... 1.10,00")
    with pytest.raises(ValueError, match="amount"):
        InsisParser().parse(text)


def test_unexpected_column_suffix_is_rejected(ordinary: str) -> None:
    text = ordinary.replace(".... 150,00", "150,00INVALID")
    with pytest.raises(ValueError, match="unexpected column content"):
        InsisParser().parse(text)


@pytest.mark.parametrize(("fixture_name", "legacy_id"), [
    ("ordinary", "2099-07-INSIS"), ("extra", "2099-07-INSIS-EXTRA"),
])
def test_reingestion_preserves_legacy_row(
    fixture_name: str, legacy_id: str, request: pytest.FixtureRequest, tmp_path,
) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    from scripts.ingest_insis import IngestionResult, run_ingestion
    from src.services.database_service import DatabaseService

    text = request.getfixturevalue(fixture_name)
    parsed = InsisParser().parse(text)
    db_path = str(tmp_path / "legacy.sqlite")
    service = DatabaseService(db_path)
    service.init_db()
    service.guardar_documento(replace(parsed, id=legacy_id, liquido_percibir=1.0))
    (tmp_path / "synthetic.pdf").touch()
    with patch("scripts.ingest_insis.parse_nomina_pdf", return_value=parsed):
        for _ in range(2):
            assert run_ingestion(tmp_path, db_path) == IngestionResult(1, 0, 0)
    rows = service.obtener_todos()
    assert len(rows) == 1
    assert rows[0]["id"] == legacy_id
    assert rows[0]["liquido_percibir"] == parsed.liquido_percibir
