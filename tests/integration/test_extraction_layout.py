"""Synthetic PDF bytes and positional evidence; no private fixtures."""
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

import pytest

from src.extraction import ExtractedDocument, ExtractedWord
from src.parsers.altran_parser import AltranParser
from src.parsers.parser_factory import ParserFactory
from src.services.ingestion_service import extract_pdf_document, parse_nomina_pdf
from tests.synthetic.parsers.test_altran_parser import SAMPLE, structured


def _pdf(amount_x: int, offset: int = 0) -> BytesIO:
    # Minimal one-page PDF, built entirely in memory with an ordinary font.
    def text(x, y, value):
        return f"BT /F1 10 Tf {x + offset} {y} Td ({value}) Tj ET\n"
    content = (text(280, 230, "Precio/%") + text(400, 230, "Devengos")
               + text(500, 230, "Deducciones")
               + text(40, 200, "ATR. 700 Cotizacion Desempleo y FP")
               + text(amount_x, 200, "100,00") + text(350, 170, "Totales")).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 400] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return BytesIO(data)


@pytest.mark.parametrize("offset", [0, 70])
def test_same_text_different_columns_from_real_extraction(offset):
    dev = extract_pdf_document(_pdf(410, offset))
    ded = extract_pdf_document(_pdf(510, offset))
    assert dev.text == ded.text
    assert dev.words and ded.words
    for document, expected in [(dev, "devengos"), (ded, "deducciones")]:
        amount = next(w for w in document.words or () if w.text == "100,00")
        assert amount.page == 1 and amount.x0 < amount.x1 and amount.top < amount.bottom
        assert AltranParser.concept_column(document, amount) == expected


def test_layout_optional_preserves_text():
    full = extract_pdf_document(_pdf(410))
    plain = extract_pdf_document(_pdf(410), include_layout=False)
    assert plain.text == full.text
    assert plain.words is None and full.words
    with pytest.raises(ValueError, match="requires layout"):
        AltranParser.concept_column(plain, full.words[-1])


def test_missing_ambiguous_or_outside_layout_rejected():
    doc = extract_pdf_document(_pdf(410))
    assert doc.words
    amount = next(w for w in doc.words if w.text == "100,00")
    missing = replace(doc, words=tuple(w for w in doc.words if w.text != "Deducciones"))
    with pytest.raises(ValueError):
        AltranParser.concept_column(missing, amount)
    outside = next(w for w in doc.words if w.text == "Totales")
    with pytest.raises(ValueError):
        AltranParser.concept_column(doc, outside)
    with pytest.raises(ValueError):
        AltranParser.concept_column(doc, replace(amount, page=2))
    crossing = replace(amount, x0=440, x1=520)
    crossed_doc = replace(doc, words=tuple(crossing if w == amount else w for w in doc.words))
    with pytest.raises(ValueError):
        AltranParser.concept_column(crossed_doc, crossing)


@pytest.mark.parametrize("company", ["altran", "coritel", "insis", "ineco", "exceltic"])
def test_existing_parsers_receive_identical_text(company):
    parser = ParserFactory().obtener_parser(company)
    expected = AltranParser().parse(SAMPLE)
    evidence = ExtractedDocument("Synthetic text", (ExtractedWord("Synthetic", 1, 2, 3, 4, 1),))
    if company == "altran":
        evidence = structured()  # Altran now also validates and consumes positional cells.
    with patch.object(parser, "parse", return_value=expected) as parse:
        assert parser.parse_extracted(evidence, "name.pdf") is expected
        parse.assert_called_once_with(evidence.text, filename="name.pdf")


def test_ingestion_dispatches_structured_evidence():
    expected = AltranParser().parse(SAMPLE)
    evidence = ExtractedDocument(SAMPLE, (ExtractedWord("Synthetic", 1, 2, 3, 4, 1),))
    parser = AltranParser()
    with patch("src.services.ingestion_service.extract_pdf_document", return_value=evidence), patch(
        "src.services.ingestion_service.ParserFactory.obtener_parser", return_value=parser
    ), patch.object(parser, "parse_extracted", return_value=expected) as parse:
        assert parse_nomina_pdf(BytesIO(), filename="synthetic.pdf") is expected
        parse.assert_called_once_with(evidence, filename="synthetic.pdf")
