"""Small shared PDF-to-model boundary; no automatic persistence."""
from io import BufferedReader, BytesIO
from pathlib import Path

import pdfplumber

from src.extraction import ExtractedDocument, ExtractedWord
from src.models.nomina import Nomina
from src.parsers.parser_factory import ParserFactory


class NoExtractableTextError(ValueError):
    """PDF requires separate treatment; never pass empty text to a parser."""



def extract_pdf_document(
    source: str | Path | BufferedReader | BytesIO, *, include_layout: bool = True,
) -> ExtractedDocument:
    """Extract text and optional real word coordinates; no rendering or OCR."""
    texts: list[str] = []
    words: list[ExtractedWord] = []
    with pdfplumber.open(source) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            texts.append(text)
            if include_layout and text.strip():
                words.extend(ExtractedWord(
                    text=w["text"], x0=float(w["x0"]), x1=float(w["x1"]),
                    top=float(w["top"]), bottom=float(w["bottom"]), page=number,
                ) for w in page.extract_words())
    return ExtractedDocument("\n".join(texts), tuple(words) if include_layout else None)

def parse_nomina_pdf(source: str | Path | BufferedReader | BytesIO, filename: str = "") -> Nomina:
    if not filename:
        filename = Path(source).name if isinstance(source, (str, Path)) else Path(str(getattr(source, "name", "document.pdf"))).name
    document = extract_pdf_document(source)
    if not document.text.strip():
        raise NoExtractableTextError("Document has no extractable text; OCR is not supported")
    parser = ParserFactory().obtener_parser(document.text + " " + filename)
    return parser.parse_extracted(document, filename=filename)
