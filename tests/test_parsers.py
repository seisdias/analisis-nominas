from src.parsers.alten_parser import AltenParser
from src.parsers.altran_parser import AltranParser
from src.parsers.exceltic_parser import ExcelticParser


def test_exceltic_parser_basic():
    # The former sample omitted company, period and table structure, accepting
    # a filename-derived period. Use the complete synthetic payroll instead.
    from tests.test_exceltic_parser import SAMPLE

    nomina = ExcelticParser().parse(SAMPLE, filename="unrelated.pdf")
    assert nomina.empresa == "EXCELTIC SL"
    assert nomina.periodo == "2098-02"
    assert nomina.liquido_percibir == 1480.00
    assert nomina.salario_base == 1200.00


def test_altran_parser_basic():
    # Identity and period now require a complete synthetic document.
    from tests.test_altran_parser import SAMPLE

    nomina = AltranParser().parse(SAMPLE, filename="unrelated.pdf")
    assert nomina.empresa == "ALTRAN INNOVACION S.L."
    assert nomina.periodo == "2098-02"
    assert nomina.liquido_percibir == 1820.00


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