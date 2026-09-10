# -*- coding: utf-8 -*-

import pytest

from src.models.documento_laboral import TipoDocumento
from src.parsers.coritel_parser import CoritelParser


def test_to_float_spanish_format() -> None:
    assert CoritelParser._to_float("1.142,86") == pytest.approx(1142.86)
    assert CoritelParser._to_float("900,01") == pytest.approx(900.01)
    assert CoritelParser._to_float("795") == pytest.approx(795.0)


def test_to_float_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="Invalid monetary value"):
        CoritelParser._to_float(".")


def test_normalize_text_preserves_dates_and_amounts() -> None:
    raw = """
    .A... .T.O.T.A.L. .D.E.V.E.N.G.A.D.O................ 1.065,13
    PERIODO DE LIQUIDACIÓN: 03.04.2006 - 30.04.2006
    """

    normalized = CoritelParser._normalize_text(raw)

    assert "TOTAL DEVENGADO" in normalized
    assert "1.065,13" in normalized
    assert "03.04.2006 - 30.04.2006" in normalized


def test_parse_ordinary_payroll() -> None:
    text = """
    CATEG/GRUPO PROF: Programador junior
    EMPRESA: Coritel, S.A. GRUPO COTIZACIÓN: 03
    CIF: A28963767
    PERIODO DE LIQUIDACIÓN: 03.04.2006 - 30.04.2006 Total días: 28

    Salario base 798,44
    Plus convenio 56,18
    Mejora voluntaria 45,39

    .A... .T.O.T.A.L. .D.E.V.E.N.G.A.D.O................ 900,01

    Contingencias Comunes 4,70 % 50,06
    .T.O.T.A.L. .A.P.O.R.T.A.C.I.O.N.E.S................ 67,64
    Retención a cta. IRPF 4 % 36,00
    Donaciones 1,37

    .B... .T.O.T.A.L. .A. .D.E.D.U.C.I.R................ 105,01
    .L.I.Q.U.I.D.O. .T.O.T.A.L. .A. .P.E.R.C.I.B.I.R. .(.A.-.B.)........ 795,00

    Prorratas pagas extraordinarias 160,72
    Base de cotización normalizada 1.065,13
    Base sujeta a retención del IRPF 900,01
    """

    nomina = CoritelParser().parse(text)

    assert nomina.anio == 2006
    assert nomina.mes == 4
    assert nomina.tipo == TipoDocumento.NOMINA_ORDINARIA

    assert nomina.salario_base == pytest.approx(798.44)
    assert nomina.plus_convenio == pytest.approx(56.18)
    assert nomina.complementos == pytest.approx(45.39)

    assert nomina.total_devengado == pytest.approx(900.01)
    assert nomina.total_deducir == pytest.approx(105.01)
    assert nomina.liquido_percibir == pytest.approx(795.00)

    assert nomina.irpf_porcentaje == pytest.approx(4.0)
    assert nomina.irpf_importe == pytest.approx(36.00)

    assert nomina.base_ss_comunes == pytest.approx(1065.13)
    assert nomina.base_irpf == pytest.approx(900.01)


def test_parse_extra_payroll() -> None:
    text = """
    CATEG/GRUPO PROF: Programador junior
    EMPRESA: Coritel, S.A. GRUPO COTIZACIÓN: 03
    CIF: A28963767
    PERIODO DE LIQUIDACIÓN: 01.07.2006 - 31.07.2006 Total días: 0

    P. Ext. S. Base Julio 427,74
    P. Ext. Plus Co. Julio 30,10
    P.Ext. Mej. Vol. Julio 24,32

    .A... .T.O.T.A.L. .D.E.V.E.N.G.A.D.O................ 482,16

    Ajuste IRPF paga extra 4 % 19,29
    Donaciones 2,87

    .B... .T.O.T.A.L. .A. .D.E.D.U.C.I.R................ 22,16
    .L.I.Q.U.I.D.O. .T.O.T.A.L. .A. .P.E.R.C.I.B.I.R. .(.A.-.B.)........ 460,00

    Base sujeta a retención del IRPF 482,16
    """

    nomina = CoritelParser().parse(text)

    assert nomina.anio == 2006
    assert nomina.mes == 7
    assert nomina.tipo == TipoDocumento.PAGA_EXTRA

    assert nomina.total_devengado == pytest.approx(482.16)
    assert nomina.total_deducir == pytest.approx(22.16)
    assert nomina.liquido_percibir == pytest.approx(460.00)

    assert nomina.irpf_porcentaje == pytest.approx(4.0)
    assert nomina.irpf_importe == pytest.approx(19.29)
    assert nomina.otras_deducciones == pytest.approx(2.87)
    assert nomina.base_irpf == pytest.approx(482.16)


def test_payroll_with_extra_pay_arrears_is_still_ordinary() -> None:
    text = """
    CATEG/GRUPO PROF: Programador junior
    EMPRESA: Coritel, S.A. GRUPO COTIZACIÓN: 03
    CIF: A28963767
    PERIODO DE LIQUIDACIÓN: 01.03.2007 - 31.03.2007 Total días: 31

    Salario base (atr.) 493,90
    Salario base 904,86
    P Ext S Base Julio (atr.) 24,69
    P Ext S Base Diciembre (atr.) 49,39
    Plus convenio 63,67
    Mejora voluntaria (atr.) -507,50
    Mejora voluntaria 174,33

    TOTAL DEVENGADO 1.529,84
    Retención a cta IRPF 11 % 168,31
    Ajuste IRPF paga extra (atr.) 0 % 0,08
    TOTAL A DEDUCIR 264,84
    LIQUIDO TOTAL A PERCIBIR 1.265,00
    Base sujeta a retención del IRPF 1.530,13
    """

    nomina = CoritelParser().parse(text)

    assert nomina.tipo == TipoDocumento.NOMINA_ORDINARIA
    assert nomina.anio == 2007
    assert nomina.mes == 3
    assert nomina.total_devengado == pytest.approx(1529.84)
    assert nomina.total_deducir == pytest.approx(264.84)
    assert nomina.liquido_percibir == pytest.approx(1265.00)


def test_missing_required_total_raises_value_error() -> None:
    text = """
    CIF: A28963767
    PERIODO DE LIQUIDACIÓN: 01.04.2006 - 30.04.2006 Total días: 30

    TOTAL A DEDUCIR 100,00
    LIQUIDO TOTAL A PERCIBIR 800,00
    """

    with pytest.raises(ValueError, match="Missing total devengado"):
        CoritelParser().parse(text)


def test_unbalanced_payroll_is_rejected() -> None:
    text = """
    CIF: A28963767
    PERIODO DE LIQUIDACIÓN: 01.04.2006 - 30.04.2006 Total días: 30

    TOTAL DEVENGADO 900,00
    TOTAL A DEDUCIR 100,00
    LIQUIDO TOTAL A PERCIBIR 750,00
    """

    with pytest.raises(ValueError, match="Payroll totals do not balance"):
        CoritelParser().parse(text)
