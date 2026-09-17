"""Synthetic Exceltic documents; no dependency on private payrolls."""
import pytest

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.exceltic_parser import ExcelticParser
from src.parsers.parser_factory import ParserFactory

SAMPLE = """EXCELTIC SL CIF B84242767
F.ALTA ANTIGU. CATEGORIA PTO.TRABAJO DEPARTAMENTO CONT.
PERIODO DEVENGADO F.COBRO DIAS
Del 01 de 02 al 28 de 02 de 2098 28-02-2098 30
1 PERCEPCIONES SUJETAS A COTIZ.AL R.G.S.S.
CUANTIA PRECIO 2 PERCEPCIONES EXCLUIDAS DE COT.AL R.G.S.S. DEVENGO DEDUCCION
CONCEPTO
Pago por transferencia
30,00 40,0000 1 SALARIO BASE 1.200,00
30,00 5,0000 1 PLUS CONVENIO 150,00
1 P.P.EXTRA 250,00
30,00 99,1234 1 MEJORA VOLUNTARIA 200,00
1 AYUDA COMIDA 70,00
1 AYUDA GUARDERIA 130,00
2 AYUDA COMIDA 70,00
2 AYUDA GUARDERIA 130,00
2 DTO. CONT. COMUNES 5,00% 100,00
2 DTO.BASE ACCIDENTE 2,00% 40,00
2 RETENCION IRPF 10,00% 180,00
DETERMINACION DE LAS BASES DE COTIZACION AL REG.GEN.DE LA SEG.SOC. TOTAL DEVENGO TOTAL DEDU.
BASE TOTAL DE COTIZACION DESG.BASES GRU IMPORTE % APOR.TRAB. 2.000,00 520,00
REMUN.TOTAL 2.000,00 REG.GRAL. 2 2.000,00 5,00 100,00 LIQUIDO TOTAL A PERCIBIR
PROR.PAG.EX. DESEMPLEO-F.P. 2.000,00 2,00 40,00
1.480,00
TOTAL 2.000,00 HORAS EXTRAS
DETERMINACIÓN DE LAS BASES DE COTIZACIÓN A LA SEGURIDAD SOCIAL Y CONCEPTOS DE RECAUDACIÓN
CONJUNTA Y DE LA BASE SUJETA A RETENCIÓN DEL IRPF Y APORTACIÓN DE LA EMPRESA
CONCEPTO BASE TIPO APORTACIÓN EMPRESA
CONTINGENCIAS COMUNES IMPORTE REMUNERACIÓN MENSUAL 2.000,00
IMPORTE PRORRATA PAGAS EXTRAORDINARIAS
TOTAL 2.000,00 23,00 460,00
AT Y EP 2.100,00 1,00 21,00
DESEMPLEO 5,00 100,00
FORMACIÓN PROFESIONAL 0,60 12,00
BASE SUJETA A RETENCIÓN DEL IRPF 1.800,00
"""


def parse(text: str = SAMPLE, filename: str = "") -> Nomina:
    return ExcelticParser().parse(text, filename)


def test_fundamentals_and_legacy_full_month_id():
    doc = parse(filename="completely-unrelated.pdf")
    assert (doc.empresa, doc.cif) == ("EXCELTIC SL", "B84242767")
    assert (doc.anio, doc.mes, doc.periodo) == (2098, 2, "2098-02")
    assert (doc.fecha_inicio, doc.fecha_fin) == ("2098-02-01", "2098-02-28")
    assert doc.id == "2098-02-EXCELTIC"
    assert doc.tipo == TipoDocumento.NOMINA_ORDINARIA
    assert (doc.total_devengado, doc.total_deducir, doc.liquido_percibir) == (2000, 520, 1480)
    assert (doc.irpf_porcentaje, doc.irpf_importe, doc.base_irpf) == (10, 180, 1800)
    assert doc.base_ss_comunes == 2000
    assert doc.base_at_ep == 2100
    assert doc.prorrata_pagas_extra is None
    assert doc.descuento_seguridad_social is None
    assert doc.otras_deducciones is None


def test_factory_identifies_document():
    assert isinstance(ParserFactory().obtener_parser(SAMPLE), ExcelticParser)


@pytest.mark.parametrize("old,new", [
    ("EXCELTIC SL", "OTRA EMPRESA SL"), ("B84242767", "B00000000"),
    ("EXCELTIC SL", "NOEXCELTIC SL"), ("B84242767", "B842427670"),
])
def test_wrong_identity_is_rejected(old, new):
    with pytest.raises(ValueError, match="identity"):
        parse(SAMPLE.replace(old, new))


def test_partial_period_and_ids_do_not_collide():
    first = parse(SAMPLE.replace("Del 01 de 02 al 28", "Del 03 de 02 al 12"))
    second = parse(SAMPLE.replace("Del 01 de 02 al 28", "Del 13 de 02 al 28"))
    assert first.fecha_inicio == "2098-02-03"
    assert first.fecha_fin == "2098-02-12"
    assert first.id == "2098-02-EXCELTIC-2098-02-03_2098-02-12"
    assert len({first.id, second.id, parse().id}) == 3


def test_same_document_has_same_complete_domain_data_regardless_of_filename():
    assert parse(filename="209801_a.pdf").to_dict() == parse(filename="renamed.pdf").to_dict()


def test_extra_and_printed_complements():
    doc = parse()
    assert (doc.salario_base, doc.plus_convenio, doc.complementos) == (1200, 150, 200)
    extra = next(c for c in doc.conceptos if c.categoria == "paga_extra_incluida")
    assert extra.importe == 250 and extra.columna == "devengos"
    assert doc.tipo == TipoDocumento.NOMINA_ORDINARIA
    improvement = next(c for c in doc.conceptos if c.concepto == "MEJORA VOLUNTARIA")
    assert (improvement.unidades, improvement.precio, improvement.importe) == (30, 99.1234, 200)


@pytest.mark.parametrize("category,amount", [("ayuda_comida", 70), ("ayuda_guarderia", 130)])
def test_mirrored_aids_are_separate_entries(category, amount):
    concepts = [c for c in parse().conceptos if c.categoria == category]
    assert [(c.columna, c.importe) for c in concepts] == [
        ("devengos", amount), ("deducciones", amount),
    ]


def test_employee_contributions_not_duplicated_or_mixed_with_employer():
    concepts = parse().conceptos
    assert len(concepts) == 11
    contributions = [c for c in concepts if c.categoria.startswith("cotizacion_")]
    assert [(c.importe, c.porcentaje, c.columna) for c in contributions] == [
        (100, 5, "deducciones"), (40, 2, "deducciones"),
    ]


def test_header_b_and_horizontal_whitespace():
    text = SAMPLE.replace("F.ALTA ANTIGU. CATEGORIA PTO.TRABAJO DEPARTAMENTO CONT.",
                          "F.ALTA ANTIGUEDAD CATEGORIA CONT.").replace(" ", "  ")
    assert parse(text).to_dict() == parse().to_dict()


@pytest.mark.parametrize("value,expected", [("0,00", 0), ("123,45", 123.45)])
def test_explicit_proration_preserved(value, expected):
    text = SAMPLE.replace("PROR.PAG.EX. DESEMPLEO", f"PROR.PAG.EX. {value} DESEMPLEO")
    text = text.replace("IMPORTE PRORRATA PAGAS EXTRAORDINARIAS\n",
                        f"IMPORTE PRORRATA PAGAS EXTRAORDINARIAS {value}\n")
    assert parse(text).prorrata_pagas_extra == expected


def test_conflicting_proration_rejected():
    text = SAMPLE.replace("PROR.PAG.EX. DESEMPLEO", "PROR.PAG.EX. 10,00 DESEMPLEO")
    text = text.replace("IMPORTE PRORRATA PAGAS EXTRAORDINARIAS\n",
                        "IMPORTE PRORRATA PAGAS EXTRAORDINARIAS 15,00\n")
    with pytest.raises(ValueError, match="proration"):
        parse(text)


@pytest.mark.parametrize("line", [
    "Del 01 de 02 al 28 de 02 de 2098 28-02-2098 30",
    "BASE TOTAL DE COTIZACION DESG.BASES GRU IMPORTE % APOR.TRAB. 2.000,00 520,00",
    "1.480,00",
])
def test_required_fields_absent_rejected(line):
    with pytest.raises(ValueError):
        parse(SAMPLE.replace(line + "\n", ""))


@pytest.mark.parametrize("bad", ["1.20,00", "150,00INVALID", "NaN", ""])
def test_invalid_amount_is_not_repaired(bad):
    with pytest.raises(ValueError):
        parse(SAMPLE.replace("1 SALARIO BASE 1.200,00", "1 SALARIO BASE " + bad))


def test_zero_net_preserved():
    text = SAMPLE.replace("2.000,00 520,00", "2.000,00 2.000,00").replace("\n1.480,00\n", "\n0,00\n")
    assert parse(text).liquido_percibir == 0


def test_absent_tax_is_not_inferred_from_outside_concepts():
    text = SAMPLE.replace("2 RETENCION IRPF 10,00% 180,00\n", "")
    text += "\n2 RETENCION IRPF 10,00% 999,00\n"
    doc = parse(text)
    assert doc.irpf_porcentaje is None and doc.irpf_importe is None


def test_absent_irpf_and_accident_bases_stay_absent():
    text = SAMPLE.replace("BASE SUJETA A RETENCIÓN DEL IRPF 1.800,00\n", "")
    text = text.replace("AT Y EP 2.100,00 1,00 21,00\n", "")
    doc = parse(text)
    assert doc.base_irpf is None and doc.base_at_ep is None


@pytest.mark.parametrize("old,new", [
    ("Del 01 de 02 al 28", "Del 29 de 02 al 28"),
    ("Del 01 de 02 al 28", "Del 01 de 02 al 31"),
    ("al 28 de 02", "al 28 de 03"),
])
def test_invalid_period_rejected(old, new):
    with pytest.raises(ValueError, match="period"):
        parse(SAMPLE.replace(old, new))


def test_common_validation_rejects_unbalanced_totals():
    with pytest.raises(ValueError, match="balance"):
        parse(SAMPLE.replace("\n1.480,00\n", "\n1.481,00\n"))


def test_unknown_concept_is_not_silently_lost():
    with pytest.raises(ValueError, match="concept"):
        parse(SAMPLE.replace("MEJORA VOLUNTARIA", "CONCEPTO DESCONOCIDO"))


def test_ambiguous_totals_rejected():
    row = "BASE TOTAL DE COTIZACION DESG.BASES GRU IMPORTE % APOR.TRAB. 2.000,00 520,00"
    with pytest.raises(ValueError):
        parse(SAMPLE.replace(row, row + "\n" + row))


def test_model_roundtrip_and_legacy_default():
    doc = parse()
    assert Nomina.from_dict(doc.to_dict()) == doc
    legacy = doc.to_dict()
    del legacy["base_at_ep"]
    assert Nomina.from_dict(legacy).base_at_ep is None
