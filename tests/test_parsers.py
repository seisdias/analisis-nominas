from src.parsers.alten_parser import AltenParser
from src.parsers.altran_parser import AltranParser
from src.parsers.exceltic_parser import ExcelticParser


def test_exceltic_parser_basic():
    parser = ExcelticParser()
    sample_text = """
    SALARIO BASE 1500,00
    PLUS CONVENIO 300,00
    P.P.EXTRA 200,00
    LIQUIDO TOTAL A PERCIBIR 1800,00
    TOTAL DEVENGO 2000,00 TOTAL DEDU. 200,00
    """
    nomina = parser.parse(sample_text, filename="209901_synthetic_exceltic.pdf")

    assert nomina.empresa == "Exceltic"
    assert nomina.periodo == "2099-01"
    assert nomina.liquido_percibir == 1800.00
    assert nomina.salario_base == 1500.00


def test_altran_parser_basic():
    parser = AltranParser()
    sample_text = """
    Salario Base 30,00 50,00 1500,00
    Plus Convenio 30,00 10,00 300,00
    Parte Proporcional Pagas Extras 200,00
    Totales 2000,00 200,00
    Líquido a percibir 1800,00
    """
    nomina = parser.parse(sample_text, filename="2099_02_synthetic_altran.pdf")

    assert nomina.empresa == "Altran"
    assert nomina.periodo == "2099-02"
    assert nomina.liquido_percibir == 1800.00


def test_alten_parser_basic():
    parser = AltenParser()
    sample_text = """
    TOTAL DEVENGADO TOTAL DEDUCCIONES 2500,00 500,00
    LIQUIDO A PERCIBIR 2000,00
    """
    nomina = parser.parse(sample_text, filename="209903_synthetic_alten.pdf")

    assert nomina.empresa == "Alten"
    assert nomina.periodo == "2099-03"
    assert nomina.liquido_percibir == 2000.00