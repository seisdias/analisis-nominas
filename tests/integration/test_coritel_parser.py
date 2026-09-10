# -*- coding: utf-8 -*-
import glob
import os

import pdfplumber
import pytest

from src.parsers.coritel_parser import CoritelParser

CORITEL_DIR = "data/testdata/coritel"


def get_coritel_pdfs():
    return glob.glob(os.path.join(CORITEL_DIR, "*.pdf"))


@pytest.mark.skipif(len(get_coritel_pdfs()) == 0, reason="No hay PDFs en data/testdata/coritel/")
@pytest.mark.parametrize("pdf_path", get_coritel_pdfs())
def test_parse_coritel_pdf(pdf_path):
    parser = CoritelParser()

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    with pytest.raises(NotImplementedError, match="Coritel extraction"):
        parser.parse(text, filename=os.path.basename(pdf_path))
