from src.parsers.alten_parser import AltenParser
from src.parsers.altran_parser import AltranParser
from src.parsers.exceltic_parser import ExcelticParser


def test_exceltic_parser_basic():
    # The former sample omitted company, period and table structure, accepting
    # a filename-derived period. Use the complete synthetic payroll instead.
    from tests.synthetic.parsers.test_exceltic_parser import SAMPLE

    nomina = ExcelticParser().parse(SAMPLE, filename="unrelated.pdf")
    assert nomina.empresa == "EXCELTIC SL"
    assert nomina.periodo == "2098-02"
    assert nomina.liquido_percibir == 1480.00
    assert nomina.salario_base == 1200.00


def test_altran_parser_basic():
    # Identity and period now require a complete synthetic document.
    from tests.synthetic.parsers.test_altran_parser import SAMPLE

    nomina = AltranParser().parse(SAMPLE, filename="unrelated.pdf")
    assert nomina.empresa == "ALTRAN INNOVACION S.L."
    assert nomina.periodo == "2098-02"
    assert nomina.liquido_percibir == 1820.00


def test_alten_parser_basic():
    # The former fixture accepted a filename-derived period and lacked identity.
    from tests.synthetic.parsers.test_alten_parser import page

    nomina = AltenParser().parse_extracted(page(), filename="190001_wrong.pdf")
    assert nomina.empresa == "ALTEN DELIVERY CENTER SPAIN SLU"
    assert nomina.periodo == "2098-02"
    assert nomina.liquido_percibir == 1259.00
