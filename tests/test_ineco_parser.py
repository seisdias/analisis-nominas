from src.parsers.ineco_parser import InecoParser


def test_ineco_parser_mock():
    sample_text = """
    01.10.2099 31.10.2099
    9001 Salario Base 1500,00
    9002 Plus Convenio 200,00
    9004 Comp.Salarial 100,00
    Total Devengos Total Deducciones
    1800,00 1800,00 400,00
    /401 Retención IRPF 15,00 270,00
    /350 Trab.cont.comunes 1800,00 115,20
    T002 Dto Base Accidente 1800,00 14,80
    Líquido a percibir: 1400,00
    Total Base: 1800,00
    Prorratas pagas extras : 300,00
    """
    parser = InecoParser()
    nomina = parser.parse(sample_text, filename="mock_ineco.pdf")

    assert nomina.anio == 2099
    assert nomina.mes == 10
    assert nomina.salario_base == 1500.00
    assert nomina.total_devengado == 1800.00
    assert nomina.total_deducir == 400.00
    assert nomina.liquido_percibir == 1400.00
