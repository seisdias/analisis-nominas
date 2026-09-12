"""Small shared PDF-to-model boundary; no automatic persistence."""
from io import BufferedReader, BytesIO
from pathlib import Path

import pdfplumber

from src.models.nomina import Nomina
from src.parsers.parser_factory import ParserFactory


class NoExtractableTextError(ValueError):
    """PDF requires separate treatment; never pass empty text to a parser."""


def parse_nomina_pdf(source: str | Path | BufferedReader | BytesIO, filename: str = "") -> Nomina:
    if not filename:
        filename = Path(source).name if isinstance(source, (str, Path)) else Path(str(getattr(source, "name", "document.pdf"))).name
    with pdfplumber.open(source) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if not text.strip():
        raise NoExtractableTextError("Document has no extractable text; OCR is not supported")
    parser = ParserFactory().obtener_parser(text + " " + filename)
    return parser.parse(text, filename=filename)
