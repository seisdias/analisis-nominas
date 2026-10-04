"""Synthetic ALTEN pages: no private amounts, dates or personal data."""

from dataclasses import replace

import pytest

from src.extraction import ExtractedDocument, ExtractedWord
from src.models.nomina import Nomina
from src.parsers.alten_parser import AltenParser


def page(
    company="ALTEN DELIVERY CENTER SPAIN SLU",
    convenio=True,
    offset=0.0,
    start="07.02.2098",
    end="28.02.2098",
):
    # Font-width coordinates are synthetic. Stream order is retained separately
    # from sorted X, including the deliberately displaced category suffix.
    chars: list[ExtractedWord] = []
    words = []
    lines = []

    def put(text, x, y):
        x += offset
        chars.extend(
            ExtractedWord(c, x + i * 5, x + (i + 1) * 5, y, y + 8, 1) for i, c in enumerate(text)
        )
        words.append(ExtractedWord(text, x, x + len(text) * 5, y, y + 8, 1))

    def line(text, y):
        lines.append(text)
        put(text, 40, y)

    line(company, 20)
    line("N.I.F.: B05366117", 32)
    put("Fecha alta:", 400, 52)
    put("01.01.2098", 460, 49)
    lines.append("Fecha alta: 01.01.2098")
    put("Profesional:", 320, 76)
    put("8Z ", 440, 73)
    put("2", 425, 73)  # PDF stream gives 8Z 2; X sorting incorrectly gives 28Z.
    put("Cotización:", 320, 94)
    put("02", 390, 91)
    if convenio:
        put("convenio:", 320, 112)
        put("TEST-NIVEL", 380, 109)
        lines.append("Categoría convenio: TEST-NIVEL")
    line(f"Periodo de liquidación del {start} al {end}", 150)
    for label, x in [
        ("CLAVE", 45),
        ("DESCRIPCIÓN", 145),
        ("UNIDAD", 295),
        ("PRECIO", 355),
        ("DEVENGOS", 420),
        ("DEDUCCIONES", 495),
    ]:
        put(label, x, 180)
    lines.append("CLAVE DESCRIPCIÓN UNIDAD PRECIO DEVENGOS DEDUCCIONES")
    rows = [
        ("9001", "Salario Base Convenio", None, None, "1.000,00", "devengos"),
        ("9003", "Plus Convenio", None, None, "100,00", "devengos"),
        ("9016", "P.P. Extra Verano", None, None, "200,00", "devengos"),
        ("PA10", "Prestaciones IT", "2,00", None, "50,00", "devengos"),
        ("PC10", "Complementos IT", None, None, "50,00", "devengos"),
        ("9030", "Bono/Variable", None, None, "100,00", "devengos"),
        ("/350", "Trab.cont.comunes", "5,00", "1.600,00", "80,00", "deducciones"),
        ("/370", "Trab.desempleo", "1,00", "1.600,00", "16,00", "deducciones"),
        ("/380", "Trab.formac.profesional", "0,25", "1.600,00", "4,00", "deducciones"),
        ("/SC0", "Trab. cuota solidaridad", None, None, "1,00", "deducciones"),
        ("/401", "Retención a cta. IRPF", "10,00", "1.400,00", "140,00", "deducciones"),
    ]
    for i, (code, label, unit, price, amount, col) in enumerate(rows):
        y = 210 + i * 14
        put(code, 45, y)
        put(label, 80, y)
        if unit:
            put(unit, 310, y)
        if price:
            put(price, 355, y)
        put(amount, 420 if col == "devengos" else 500, y)
        lines.append(" ".join(t for t in (code, label, unit, price, amount) if t))
    line("1.500,00 241,00", 390)
    line("LIQUIDO A PERCIBIR 1.259,00", 405)
    line("COTIZACIÓN PATRONAL", 425)
    line("Base sujeta a retención IRPF 1.400,00", 445)
    footer = [
        ("REM. TOTAL", 50),
        ("PRORRATA", 125),
        ("PROR.OTROS", 190),
        ("BASE S.S.", 260),
        ("BASE A.T./E.P.", 330),
        ("BASE IRPF", 420),
        ("BASE IRPF Esp", 500),
    ]
    for label, x in footer:
        put(label, x, 470)
    lines.append(" ".join(label for label, x in footer))
    for value, x in [
        ("1.500,00", 52),
        ("30,00", 198),
        ("1.600,00", 264),
        ("1.700,00", 345),
        ("1.400,00", 425),
    ]:
        put(value, x, 485)
    line("VALORES ACUMULADOS AÑO", 510)
    line("BASE IRPF 90.000,00 RETENCION 9.000,00", 524)
    return ExtractedDocument("\n".join(lines), tuple(words), characters=tuple(chars))


def test_page_fundamentals():
    n = AltenParser().parse_extracted(page(), "190001_wrong.pdf")
    assert (n.empresa, n.cif) == ("ALTEN DELIVERY CENTER SPAIN SLU", "B05366117")
    assert (n.fecha_inicio, n.fecha_fin) == ("2098-02-07", "2098-02-28")
    assert (n.total_devengado, n.total_deducir, n.liquido_percibir) == (1500, 241, 1259)
    assert (n.base_irpf, n.irpf_porcentaje, n.irpf_importe) == (1400, 10, 140)
    assert (n.base_irpf_pie, n.base_sujeta_retencion_irpf) == (1400, 1400)
    assert (n.base_ss_comunes, n.base_at_ep, n.pror_otros) == (1600, 1700, 30)
    assert n.prorrata_pagas_extra is None and n.base_irpf_especie is None
    assert n.descuento_seguridad_social is None and n.otras_deducciones is None
    assert n.complementos is None
    assert (n.fecha_alta, n.categoria, n.grupo_cotizacion, n.categoria_convenio) == (
        "2098-01-01",
        "8Z 2",
        "02",
        "TEST-NIVEL",
    )
    assert n.tipo.value == "NOMINA_ORDINARIA"
    assert len(n.conceptos) == 11
    assert Nomina.from_dict(n.to_dict()) == n


@pytest.mark.parametrize(
    "company,convenio,family",
    [
        ("ALTEN S.P.A.IN. S.A.", False, "N1a"),
        ("ALTEN DELIVERY CENTER SPAIN SLU", False, "N1b"),
        ("ALTEN DELIVERY CENTER SPAIN SLU", True, "N2"),
    ],
)
def test_templates(company, convenio, family):
    doc = page(company, convenio)
    assert AltenParser.template(doc.text) == family
    assert AltenParser().parse_extracted(doc).empresa == company


def test_columns_are_geometry_not_codes():
    doc = page()
    chars = tuple(
        replace(c, x0=c.x0 - 80, x1=c.x1 - 80) if c.top == 210 + 9 * 14 and c.x0 >= 500 else c
        for c in doc.characters or ()
    )
    n = AltenParser().parse_extracted(replace(doc, characters=chars))
    assert next(c for c in n.conceptos if c.codigo == "/SC0").columna == "devengos"


def test_filename_and_geometry_translation():
    parser = AltenParser()
    assert parser.parse_extracted(page(), "wrong.pdf") == parser.parse_extracted(
        page(offset=75), "other.pdf"
    )


def test_page_versions_are_not_selected():
    a = page()
    b = replace(
        a, text=a.text.replace("1.500,00 241,00", "1.500,00 250,00").replace("1.259,00", "1.250,00")
    )
    container = ExtractedDocument(a.text + "\n" + b.text, pages=(a, b))
    results = AltenParser().parse_pages(container)
    assert len(results) == 2 and results[0].id == results[1].id
    assert [n.total_deducir for n in results] == [241, 250]
    with pytest.raises(ValueError, match="page"):
        AltenParser().parse_extracted(container)


def test_plain_text_contract_preserves_printed_fundamentals():
    n = AltenParser().parse(page().text, "wrong.pdf")
    assert n.periodo == "2098-02" and n.liquido_percibir == 1259
    assert n.conceptos == [] and n.base_ss_comunes is None
    with pytest.raises(ValueError, match="layout"):
        AltenParser().parse_extracted(ExtractedDocument(page().text))


@pytest.mark.parametrize(
    "old,new",
    [
        ("B05366117", "A28250271"),
        ("B05366117", "XB05366117"),
        ("ALTEN DELIVERY CENTER SPAIN SLU", "OTHER SL"),
        ("07.02.2098", "30.02.2098"),
        ("Periodo de liquidación", "Fecha cualquiera"),
        ("1.500,00 241,00", ""),
        ("1.500,00 241,00", "1.50,00 241,00"),
        ("1.500,00 241,00", "1.500,00 241,00INVALID"),
        ("LIQUIDO A PERCIBIR 1.259,00", "LIQUIDO A PERCIBIR"),
        ("1.259,00", "1.250,00"),
    ],
)
def test_invalid_fundamentals(old, new):
    with pytest.raises(ValueError):
        AltenParser().parse(page().text.replace(old, new))


def test_certificate_rejected():
    with pytest.raises(ValueError):
        AltenParser().parse(
            "ALTEN DELIVERY CENTER SPAIN SLU B05366117 Certificado de retenciones 2098"
        )


def test_model_old_payload_compatible():
    n = Nomina(id="synthetic", anio=2098, mes=2, periodo="2098-02", empresa="Example", cif="TEST")
    old = {
        k: v
        for k, v in n.to_dict().items()
        if k
        not in {
            "pror_otros",
            "base_irpf_pie",
            "base_irpf_especie",
            "base_sujeta_retencion_irpf",
            "fecha_alta",
            "categoria_convenio",
        }
    }
    assert Nomina.from_dict(old) == n


def _glyphs(text, x, y, page_number=1):
    return tuple(
        ExtractedWord(c, x + i * 5, x + (i + 1) * 5, y, y + 8, page_number)
        for i, c in enumerate(text)
    )


def test_all_economic_semantics():
    n = AltenParser().parse_extracted(page())
    rows = {c.codigo: c for c in n.conceptos}
    assert rows["9001"].importe == 1000 and rows["9001"].categoria == "salario_base"
    assert rows["9016"].categoria == "paga_extra_incluida"
    assert rows["9030"].categoria == "variable"
    assert rows["PA10"].unidades == 2 and rows["PA10"].importe == 50
    assert rows["PC10"].categoria == "complemento_it"
    assert (rows["/401"].porcentaje, rows["/401"].base, rows["/401"].importe) == (10, 1400, 140)
    assert (rows["/350"].porcentaje, rows["/350"].base, rows["/350"].importe) == (5, 1600, 80)
    assert rows["/SC0"].importe == 1 and rows["/SC0"].base is None
    assert all(not c.atraso for c in n.conceptos)
    assert n.tipo.value == "NOMINA_ORDINARIA"


def test_independent_footer_irpf_base():
    doc = page()
    chars = tuple(c for c in doc.characters or () if not (c.top == 485 and 420 <= c.x0 < 490))
    chars += _glyphs("1.300,00", 425, 485)
    n = AltenParser().parse_extracted(replace(doc, characters=chars))
    assert n.base_irpf == 1400 and n.base_sujeta_retencion_irpf == 1400
    assert n.base_irpf_pie == 1300


def test_printed_zero_and_blank_footer_are_distinct():
    doc = page()
    chars = tuple(c for c in doc.characters or () if not (c.top == 485 and 190 <= c.x0 < 250))
    chars += _glyphs("0,00", 130, 485)
    n = AltenParser().parse_extracted(replace(doc, characters=chars))
    assert n.pror_otros is None
    assert n.prorrata_pagas_extra == 0


def test_zero_net_is_preserved():
    doc = page()
    text = doc.text.replace("1.500,00 241,00", "241,00 241,00").replace("1.259,00", "0,00")
    n = AltenParser().parse(text)
    assert n.liquido_percibir == 0 and n.total_devengado == 241


def test_irpf_absence_not_filled_from_footer_or_external_row():
    doc = page()
    tax_top = 210 + 10 * 14
    text = "\n".join(line for line in doc.text.splitlines() if not line.startswith("/401"))
    text += "\n/401 Retención a cta. IRPF 9,00 2.000,00 180,00"
    doc = replace(
        doc,
        text=text,
        words=tuple(w for w in doc.words or () if w.top != tax_top),
        characters=tuple(c for c in doc.characters or () if c.top != tax_top),
    )
    n = AltenParser().parse_extracted(doc)
    assert n.irpf_importe is n.irpf_porcentaje is n.base_irpf is None
    assert n.base_irpf_pie == 1400
    assert all(c.codigo != "/401" for c in n.conceptos)


def test_unknown_and_repeated_codes_are_not_aggregated():
    doc = page()
    y = 365
    text = doc.text.replace(
        "1.500,00 241,00", "9001 Concepto sintético adicional 12,00\n1.500,00 241,00"
    )
    new_words = (ExtractedWord("9001", 45, 65, y, y + 8, 1),)
    chars = (
        _glyphs("9001", 45, y)
        + _glyphs("Concepto sintético adicional", 80, y)
        + _glyphs("12,00", 420, y)
    )
    n = AltenParser().parse_extracted(
        replace(doc, text=text, words=doc.words + new_words, characters=doc.characters + chars)
    )
    assert len(n.conceptos) == 12
    assert [c.importe for c in n.conceptos if c.codigo == "9001"] == [1000, 12]
    assert n.conceptos[-1].categoria == "otro"
    assert n.conceptos[-1].concepto == "Concepto sintético adicional"


def test_employer_contributions_excluded():
    doc = page()
    y = 430
    chars = _glyphs("/350", 45, y) + _glyphs("Trab.cont.comunes", 80, y) + _glyphs("999,00", 500, y)
    text = doc.text.replace(
        "COTIZACIÓN PATRONAL", "COTIZACIÓN PATRONAL\n/350 Trab.cont.comunes 999,00"
    )
    n = AltenParser().parse_extracted(
        replace(
            doc,
            text=text,
            words=doc.words + (ExtractedWord("/350", 45, 65, y, y + 8, 1),),
            characters=doc.characters + chars,
        )
    )
    assert len([c for c in n.conceptos if c.codigo == "/350"]) == 1
    assert next(c.importe for c in n.conceptos if c.codigo == "/350") == 80


def test_ambiguous_column_rejected():
    doc = page()
    # Cross the midpoint between DEVENGOS and DEDUCCIONES.
    chars = tuple(
        replace(c, x0=c.x0 + 42, x1=c.x1 + 42) if c.top == 210 and c.x0 >= 420 else c
        for c in doc.characters or ()
    )
    with pytest.raises(ValueError, match="column"):
        AltenParser().parse_extracted(replace(doc, characters=chars))


def test_corrupted_numeric_cell_rejected():
    doc = page()
    chars = doc.characters + _glyphs("INVALID", 530, 210)
    with pytest.raises(ValueError, match="number"):
        AltenParser().parse_extracted(replace(doc, characters=chars))


def test_mixed_page_glyphs_rejected():
    doc = page()
    chars = tuple(replace(c, page=2) for c in doc.characters or ())
    with pytest.raises(ValueError, match="page"):
        AltenParser().parse_extracted(replace(doc, characters=chars))


@pytest.mark.parametrize(
    "start,end,identifier",
    [
        ("01.02.2098", "28.02.2098", "2098-02-ALTEN"),
        ("07.02.2098", "28.02.2098", "2098-02-ALTEN-2098-02-07_2098-02-28"),
        ("01.02.2098", "14.02.2098", "2098-02-ALTEN-2098-02-01_2098-02-14"),
    ],
)
def test_period_identity(start, end, identifier):
    n = AltenParser().parse_extracted(page(start=start, end=end))
    assert n.id == identifier
    assert AltenParser.period_key(n) == f"B05366117|{n.fecha_inicio}|{n.fecha_fin}|NOMINA_ORDINARIA"


def test_no_automatic_economic_ingestion():
    from io import BytesIO
    from unittest.mock import patch

    from src.services.ingestion_service import parse_nomina_pdf

    with patch("src.services.ingestion_service.extract_pdf_document", return_value=page()):
        with pytest.raises(ValueError, match="economic ingestion is disabled"):
            parse_nomina_pdf(BytesIO(), "synthetic.pdf")


def _multipage_pdf():
    """Two text pages and one blank page, generated in memory without dependencies."""
    from io import BytesIO

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>",
    ]
    for text in ["First", "Second", ""]:
        stream = f"BT /F1 10 Tf 40 100 Td ({text}) Tj ET".encode()
        content_id = len(objects) + 2
        objects.extend(
            [
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 9 0 R >> >> /Contents {content_id} 0 R >>".encode(),
                f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
            ]
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return BytesIO(data)


def test_real_page_extraction_preserves_blank_pages_and_old_text():
    from src.services.ingestion_service import extract_pdf_document

    full = extract_pdf_document(_multipage_pdf())
    plain = extract_pdf_document(_multipage_pdf(), include_layout=False)
    assert full.pages and plain.pages and len(full.pages) == len(plain.pages) == 3
    assert [p.text for p in full.pages] == ["First", "Second", ""]
    assert full.text == plain.text == "First\nSecond\n"
    assert full.pages[0].words is not None
    assert {w.page for w in full.pages[0].words} == {1}
    assert full.pages[1].characters is not None
    assert {c.page for c in full.pages[1].characters} == {2}
    assert full.pages[2].words == full.pages[2].characters == ()
    assert plain.words is plain.characters is None
    assert all(p.words is p.characters is None for p in plain.pages)
