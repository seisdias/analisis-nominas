"""Small shared PDF-to-model boundary; no automatic persistence."""
from io import BufferedReader, BytesIO
from pathlib import Path

import pdfplumber

from src.extraction import ExtractedDocument, ExtractedWord
from src.models.nomina import Nomina
from src.parsers.alten_parser import AltenParser
from src.parsers.parser_factory import ParserFactory


class NoExtractableTextError(ValueError):
    """PDF requires separate treatment; never pass empty text to a parser."""



def extract_pdf_document(
    source: str | Path | BufferedReader | BytesIO, *, include_layout: bool = True,
) -> ExtractedDocument:
    """Extract text and optional real word coordinates; no rendering or OCR."""
    pages: list[ExtractedDocument] = []
    with pdfplumber.open(source) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            def evidence(items) -> tuple[ExtractedWord, ...]:
                return tuple(ExtractedWord(
                    text=w["text"], x0=float(w["x0"]), x1=float(w["x1"]),
                    top=float(w["top"]), bottom=float(w["bottom"]), page=number,
                ) for w in items)
            words = evidence(page.extract_words()) if include_layout else None
            characters = evidence(page.chars) if include_layout else None
            pages.append(ExtractedDocument(text, words, characters))
    return ExtractedDocument(
        "\n".join(p.text for p in pages),
        tuple(w for p in pages for w in p.words or ()) if include_layout else None,
        tuple(c for p in pages for c in p.characters or ()) if include_layout else None,
        tuple(pages),
    )

def parse_nomina_pdf(source: str | Path | BufferedReader | BytesIO, filename: str = "") -> Nomina:
    if not filename:
        filename = Path(source).name if isinstance(source, (str, Path)) else Path(str(getattr(source, "name", "document.pdf"))).name
    document = extract_pdf_document(source)
    if not document.text.strip():
        raise NoExtractableTextError("Document has no extractable text; OCR is not supported")
    parser = ParserFactory().obtener_parser(document.text + " " + filename)
    if isinstance(parser, AltenParser):
        raise ValueError("ALTEN economic ingestion is disabled; use AltenParser.parse_pages for documentary parsing")
    return parser.parse_extracted(document, filename=filename)
