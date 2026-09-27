"""Portable synthetic payrolls; no private corpus amounts or personal data."""
import pytest

from src.parsers.altran_parser import AltranParser

SAMPLE = """ALTRAN INNOVACION S.L.
CIF: B80428972
Del01al28deFEBRERO 2098 30
Periodo Código Concepto Cantidad/Base Precio/% Devengos Deducciones
02/98 R1A Salario Base 30,00 50,0000 1.500,00
02/98 R1B Plus Convenio 30,00 3,3333 100,00
02/98 R1R Mejora Voluntaria 30,00 10,0000 300,00
02/98 R1X Parte Proporcional Pagas Extras 230,00
02/98 FE4 Retención I.R.P.F. Especie 10,00 12,5000 1,25
02/98 F74 Retención I.R.P.F. 2.050,00 12,5000 256,25
Seguridad Social Totales 2.130,00 310,00
Contigencias Accidente Prorrata Horas Extras Líquido a percibir 1.820,00
Comunes de Trabajo Pagas Extras Normales F.Mayor
2.600,00 2.700,00 230,00 Sello y firma:
Cotización Empresa
Acumulados
Imponible I.R.P.F. Retención I.R.P.F. Cotización S.S.
90.000,00 20.000,00 5.000,00
"""


def test_fundamentals():
    n = AltranParser().parse(SAMPLE, "209901_wrong.pdf")
    assert (n.empresa, n.cif) == ("ALTRAN INNOVACION S.L.", "B80428972")
    assert (n.fecha_inicio, n.fecha_fin, n.periodo) == ("2098-02-01", "2098-02-28", "2098-02")
    assert n.id == "2098-02-ALTRAN"
    assert (n.total_devengado, n.total_deducir, n.liquido_percibir) == (2130, 310, 1820)
    assert (n.base_irpf, n.irpf_porcentaje, n.irpf_importe) == (2050, 12.5, 256.25)
    assert (n.base_ss_comunes, n.base_at_ep, n.prorrata_pagas_extra) == (2600, 2700, 230)
    assert (n.salario_base, n.plus_convenio, n.complementos) == (1500, 100, 300)
    assert n.descuento_seguridad_social is None and n.otras_deducciones is None
    assert n.tipo.value == "NOMINA_ORDINARIA"
    assert n.conceptos == []


@pytest.mark.parametrize("filename", ["", "renamed.pdf", "201104_wrong.pdf"])
def test_filename_independence(filename):
    assert AltranParser().parse(SAMPLE, filename) == AltranParser().parse(SAMPLE)


@pytest.mark.parametrize("period,start,end", [
    ("Del07al31deMarzo 2016 25", "2016-03-07", "2016-03-31"),
    ("Del 01 al 30 de NOVIEMBRE 2017 30", "2017-11-01", "2017-11-30"),
    ("Del01al31deDICIEMBRE 2017 30", "2017-12-01", "2017-12-31"),
    ("Del01al31deENERO 2022 30", "2022-01-01", "2022-01-31"),
])
def test_document_period(period, start, end):
    text = SAMPLE.replace("Del01al28deFEBRERO 2098 30", period)
    text = text.replace("02/98", f"{start[5:7]}/{start[2:4]}")
    n = AltranParser().parse(text)
    assert (n.fecha_inicio, n.fecha_fin) == (start, end)
    expected = start[:7] + "-ALTRAN"
    if start[-2:] != "01":
        expected += f"-{start}_{end}"
    assert n.id == expected


def test_partial_end_distinguishes_identity():
    text = SAMPLE.replace("Del01al28", "Del01al14")
    assert AltranParser().parse(text).id == "2098-02-ALTRAN-2098-02-01_2098-02-14"


@pytest.mark.parametrize("old,new", [
    ("ALTRAN INNOVACION S.L.", "OTHER COMPANY SL"),
    ("B80428972", "B00000000"),
    ("CIF: B80428972", ""),
    ("Del01al28deFEBRERO 2098 30", ""),
    ("Del01al28", "Del31al28"),
    ("FEBRERO", "UNKNOWN"),
    ("Seguridad Social Totales 2.130,00 310,00", ""),
    ("Líquido a percibir 1.820,00", "Líquido a percibir"),
    ("1.820,00", "1.800,00"),
    ("2.130,00 310,00", "2.13,00 310,00"),
    ("2.130,00 310,00", "2.130,00 310,00INVALID"),
])
def test_invalid_required_fields(old, new):
    with pytest.raises(ValueError):
        AltranParser().parse(SAMPLE.replace(old, new))


def test_optional_absence_is_not_zero():
    text = "\n".join(line for line in SAMPLE.splitlines() if " F74 " not in line)
    text = text.replace("2.600,00 2.700,00 230,00 Sello y firma:", "Sello y firma:")
    n = AltranParser().parse(text)
    assert n.base_irpf is n.irpf_porcentaje is n.irpf_importe is None
    assert n.base_ss_comunes is n.base_at_ep is n.prorrata_pagas_extra is None


def test_printed_zero_preserved():
    text = SAMPLE.replace("2.050,00 12,5000 256,25", "0,00 0,0000 0,00")
    text = text.replace("2.600,00 2.700,00 230,00", "0,00 0,00 0,00")
    text = text.replace("2.130,00 310,00", "310,00 310,00").replace("1.820,00", "0,00")
    n = AltranParser().parse(text)
    assert (n.base_irpf, n.irpf_porcentaje, n.irpf_importe) == (0, 0, 0)
    assert (n.base_ss_comunes, n.base_at_ep, n.prorrata_pagas_extra) == (0, 0, 0)
    assert n.liquido_percibir == 0


def test_atr_and_paid_extra_do_not_supply_footer_proration():
    # Synthetic values deliberately differ from the private corpus.
    text = SAMPLE.replace("02/98 R1X", "ATR. R1X Parte Proporcional Pagas Extras 19,75\n02/98 R1X")
    text = text.replace("Pagas Extras 230,00", "Pagas Extras 410,00")
    text = text.replace("Normales F.Mayor", "Ordina. Compl.").replace("Horas Extras", "Horas")
    assert AltranParser().parse(text).prorrata_pagas_extra == 230


def test_irpf_outside_table_is_ignored():
    text = "\n".join(line for line in SAMPLE.splitlines() if " F74 " not in line)
    text += "\n02/98 F74 Retención I.R.P.F. 9.000,00 40,0000 3.600,00"
    assert AltranParser().parse(text).irpf_importe is None


@pytest.mark.parametrize("line", [
    "02/98 F74 Retención I.R.P.F. 2.050,00 12,5000 256,25",
    "Seguridad Social Totales 2.130,00 310,00",
])
def test_ambiguous_rows_rejected(line):
    with pytest.raises(ValueError):
        AltranParser().parse(SAMPLE.replace(line, line + "\n" + line))


@pytest.mark.parametrize("replacement", ["2.600,00 230,00", "2.600,00INVALID 2.700,00 230,00"])
def test_ambiguous_or_invalid_footer_rejected(replacement):
    with pytest.raises(ValueError):
        AltranParser().parse(SAMPLE.replace("2.600,00 2.700,00 230,00", replacement))


def test_legacy_scalar_absence_rejected_instead_of_fabricated_zero():
    text = "\n".join(line for line in SAMPLE.splitlines() if " R1R " not in line)
    with pytest.raises(ValueError):
        AltranParser().parse(text)


@pytest.mark.parametrize("text", [
    "",
    "ALTRAN INNOVACION S.L.\nCIF: B80428972\nCertificado de retenciones ejercicio 2098",
    "ALTRAN INNOVACION S.L.\nCIF: B80428972\nCARTA DE FINIQUITO",
])
def test_non_payroll_rejected(text):
    with pytest.raises(ValueError):
        AltranParser().parse(text, "209802.pdf")

def test_company_and_recipient_heading_on_same_line():
    text = SAMPLE.replace("ALTRAN INNOVACION S.L.", "ALTRAN INNOVACION S.L. Señor/a")
    assert AltranParser().parse(text).empresa == "ALTRAN INNOVACION S.L."

# Structured synthetic rows: period, code, description, quantity/base, price/rate,
# devengo, deduction. Values are fictitious and not copied from private PDFs.
ROWS = [
    ("02/98", "R1A", "Salario Base", "30,00", "50,0000", "1.500,00", None),
    ("02/98", "R1B", "Plus Convenio", "30,00", "3,3333", "100,00", None),
    ("02/98", "R1R", "Mejora Voluntaria", "30,00", "10,0000", "300,00", None),
    ("02/98", "R1X", "Parte Proporcional Pagas Extras", None, None, "230,00", None),
    ("02/98", "FE4", "Retención I.R.P.F. Especie", "10,00", "12,5000", None, "1,25"),
    ("02/98", "F74", "Retención I.R.P.F.", "2.050,00", "12,5000", None, "256,25"),
]


def structured(rows=None, extra_rows=(), *, offset=0):
    from src.extraction import ExtractedDocument, ExtractedWord

    rows = list(ROWS if rows is None else rows) + list(extra_rows)
    words = []
    def word(text, x0, x1, top):
        words.append(ExtractedWord(text, x0 + offset, x1 + offset, top, top + 8, 1))
    headings = [("Periodo", 30, 60), ("Código", 80, 108), ("Concepto", 130, 166),
                ("Cantidad/Base", 400, 458), ("Precio/%", 490, 528),
                ("Devengos", 600, 638), ("Deducciones", 700, 750)]
    for label, left, right in headings:
        word(label, left, right, 100)
    lines = []
    for index, row in enumerate(rows):
        marker, code, description, quantity, price, dev, ded = row
        top = 115 + index * 14
        word(marker, 30, 30 + len(marker) * 4, top)
        word(code, 82, 82 + len(code) * 4, top)
        x = 130
        for token in description.split():
            word(token, x, x + len(token) * 4, top)
            x += (len(token) + 1) * 4
        for value, right in [(quantity, 458), (price, 528), (dev, 638), (ded, 750)]:
            if value is not None:
                word(value, right - len(value) * 4, right, top)
        lines.append(" ".join(str(value) for value in row if value is not None))
    end = 115 + len(rows) * 14
    word("Totales", 500, 532, end)
    # Employer data exists below the table and must not be treated as a concept.
    word("EMP", 82, 94, end + 30)
    word("999,00", 614, 638, end + 30)
    header, footer = SAMPLE.split("02/98 R1A", 1)[0], SAMPLE[SAMPLE.index("Seguridad Social Totales"):]
    return ExtractedDocument(header + "\n".join(lines) + "\n" + footer, tuple(words))


def test_structured_fundamentals_and_tax_concepts():
    from dataclasses import replace

    n = AltranParser().parse_extracted(structured(), "misleading.pdf")
    assert replace(n, conceptos=[]) == AltranParser().parse(SAMPLE)
    assert len(n.conceptos) == len(ROWS)
    tax = next(c for c in n.conceptos if c.codigo == "F74")
    specie = next(c for c in n.conceptos if c.codigo == "FE4")
    assert (tax.base, tax.porcentaje, tax.importe) == (2050, 12.5, 256.25)
    assert tax.unidades is tax.precio is None
    assert (specie.base, specie.porcentaje, specie.importe) == (10, 12.5, 1.25)
    assert tax.columna == specie.columna == "deducciones"
    salary = n.conceptos[0]
    assert (salary.unidades, salary.precio, salary.importe) == (30, 50, 1500)
    assert salary.base is salary.porcentaje is None


@pytest.mark.parametrize("offset", [0, 85])
def test_repetition_atr_and_columns(offset):
    extras = [
        ("02/98", "R2R", "Actuaciones", None, None, "40,00", None),
        ("02/98", "R2R", "Disponibilidad", None, None, "60,00", None),
        ("ATR.", "700", "Cotización Desempleo y FP", None, None, "2,00", None),
        ("ATR.", "700", "Cotización Desempleo y FP", None, None, None, "2,00"),
        ("02/98", "700", "Cotización Desempleo y FP", "500,00", "1,5000", None, "7,50"),
    ]
    n = AltranParser().parse_extracted(structured(extra_rows=extras, offset=offset))
    tail = n.conceptos[-5:]
    assert [c.categoria for c in tail[:2]] == ["actuaciones", "disponibilidad"]
    assert [c.concepto for c in tail[:2]] == ["Actuaciones", "Disponibilidad"]
    assert [c.atraso for c in tail[2:]] == [True, True, False]
    assert [c.columna for c in tail[2:]] == ["devengos", "deducciones", "deducciones"]
    assert [c.importe for c in tail[2:]] == [2, 2, 7.5]
    assert tail[2].base is tail[2].porcentaje is None
    assert (tail[4].base, tail[4].porcentaje) == (500, 1.5)
    assert n.descuento_seguridad_social is None


@pytest.mark.parametrize("code,description,category", [
    ("R1C", "Antigüedad", "antiguedad"),
    ("R2L", "Compensación Jornada Intensiva", "compensacion_jornada_intensiva"),
    ("R3A", "Compensa Comida", "compensacion_comida"),
    ("R3C", "Compensa Guardería", "compensacion_guarderia"),
    ("R3E", "Compensa Salud", "compensacion_salud"),
    ("R3F", "Compensa Transporte", "compensacion_transporte"),
    ("R3Z", "Comida Devolución Saldo", "devolucion_saldo_comida"),
    ("R3H", "Transporte Devolución Saldo", "devolucion_saldo_transporte"),
    ("R3L", "Ayuda ADSL", "ayuda_adsl"),
    ("R4L", "Ayuda ADSL", "ayuda_adsl"),
    ("R5S", "Ayuda Teletrabajo", "ayuda_teletrabajo"),
    ("R5J", "Compensación Cesta Navidad", "compensacion_cesta_navidad"),
    ("A29", "Prestación 12 Días Siguientes Empresa", "prestacion_it_empresa"),
    ("S75", "Prestación Enfermedad", "prestacion_it"),
    ("R1W", "Complemento IT/AT/MAT", "complemento_it_at_mat"),
    ("R2T", "Gratificación Extraordinaria", "gratificacion_extraordinaria"),
    ("R3Q", "Horas Extras", "horas_extra"),
    ("ZZZ", "Concepto no catalogado", "otro"),
])
def test_concept_families_without_inferred_totals(code, description, category):
    n = AltranParser().parse_extracted(structured(extra_rows=[
        ("02/98", code, description, None, None, "45,67", None),
    ]))
    c = n.conceptos[-1]
    assert (c.codigo, c.concepto, c.categoria, c.importe) == (code, description, category, 45.67)
    assert c.base is c.unidades is c.precio is c.porcentaje is None
    assert (n.total_devengado, n.total_deducir, n.liquido_percibir) == (2130, 310, 1820)
    assert n.tipo.value == "NOMINA_ORDINARIA"


@pytest.mark.parametrize("code,description", [
    ("700", "Cotización Desempleo y FP"),
    ("705", "Cotización Contingencias Comunes"),
    ("707", "COTIZACION HORAS EXTRAS NORMALES"),
])
def test_individual_contributions(code, description):
    n = AltranParser().parse_extracted(structured(extra_rows=[
        ("02/98", code, description, "800,00", "2,0000", None, "16,00"),
    ]))
    c = n.conceptos[-1]
    assert (c.base, c.porcentaje, c.importe, c.columna) == (800, 2, 16, "deducciones")
    assert c.unidades is c.precio is None
    assert n.descuento_seguridad_social is None
    assert all(c.codigo != "EMP" for c in n.conceptos)


@pytest.mark.parametrize("dev_code,dev_desc,ded_code,ded_desc", [
    ("U2P", "Valor Seguro Salud", "U3P", "Dto. Seguro Salud"),
    ("U3C", "Ret.Esp.Seg.Vida / Accidente", "U3D", "Dto.Ret.Esp.Seg.Vida / Accidente"),
    ("U2M", "Cotización Ticket Jornada Intensiva", "U3M", "Dto. Ticket Jornada Intensiva"),
])
def test_opposite_entries_not_cancelled(dev_code, dev_desc, ded_code, ded_desc):
    n = AltranParser().parse_extracted(structured(extra_rows=[
        ("02/98", dev_code, dev_desc, None, None, "25,00", None),
        ("02/98", ded_code, ded_desc, None, None, None, "25,00"),
    ]))
    assert len(n.conceptos) == len(ROWS) + 2
    assert [c.columna for c in n.conceptos[-2:]] == ["devengos", "deducciones"]
    assert [c.importe for c in n.conceptos[-2:]] == [25, 25]


def test_extra_adjustment_does_not_replace_proration():
    n = AltranParser().parse_extracted(structured(extra_rows=[
        ("ATR.", "R1X", "Parte Proporcional Pagas Extras", None, None, None, "19,75"),
    ]))
    assert n.prorrata_pagas_extra == 230
    c = n.conceptos[-1]
    assert (c.importe, c.atraso, c.columna) == (19.75, True, "deducciones")
    assert n.tipo.value == "NOMINA_ORDINARIA"


def test_absent_specie_and_real_zero():
    n = AltranParser().parse_extracted(structured(
        rows=[r for r in ROWS if r[1] != "FE4"], extra_rows=[
            ("02/98", "705", "Cotización Contingencias Comunes", "0,00", "0,0000", None, "0,00"),
        ]))
    assert all(c.codigo != "FE4" for c in n.conceptos)
    c = n.conceptos[-1]
    assert (c.base, c.porcentaje, c.importe) == (0, 0, 0)


@pytest.mark.parametrize("amount,expected", [("-12,34", -12.34), ("12,34-", -12.34)])
def test_printed_sign_and_notation(amount, expected):
    n = AltranParser().parse_extracted(structured(extra_rows=[
        ("ATR.", "ZZZ", "Ajuste no catalogado", None, None, amount, None),
    ]))
    assert n.conceptos[-1].importe == expected
    assert n.conceptos[-1].importe_texto == amount


def test_layout_required_for_exhaustive_parsing():
    from src.extraction import ExtractedDocument
    with pytest.raises(ValueError, match="layout"):
        AltranParser().parse_extracted(ExtractedDocument(SAMPLE))


def test_ambiguous_layout_rejected():
    from dataclasses import replace
    doc = structured()
    assert doc.words
    words = tuple(replace(w, x0=635, x1=715) if w.text == "1,25" else w for w in doc.words)
    with pytest.raises(ValueError):
        AltranParser().parse_extracted(replace(doc, words=words))


def test_missing_layout_row_rejected_not_silently_dropped():
    from dataclasses import replace
    doc = structured()
    assert doc.words
    marker = next(w for w in doc.words if w.text == "FE4")
    words = tuple(w for w in doc.words if w.top != marker.top)
    with pytest.raises(ValueError):
        AltranParser().parse_extracted(replace(doc, words=words))
