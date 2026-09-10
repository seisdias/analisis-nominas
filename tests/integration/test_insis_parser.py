from pathlib import Path

import pdfplumber
import pytest

from src.parsers.insis_parser import InsisParser

INSIS_DIR = Path("data/testdata/insis4")
INSIS_FILES = sorted(list(INSIS_DIR.glob("*.pdf"))) if INSIS_DIR.exists() else []


@pytest.mark.parametrize("pdf_path", INSIS_FILES, ids=lambda p: p.name)
def test_parse_insis_pdf(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

    parser = InsisParser()
    nomina = parser.parse(text, filename=pdf_path.name)

    # Validaciones fundamentales
    assert nomina.empresa == "INTELIGENCIA SISTEMATICA 4, S.L."
    assert nomina.cif == "B84225283"
    assert nomina.total_devengado > 0
    assert nomina.liquido_percibir > 0
    assert nomina.anio >= 2000
    assert 1 <= nomina.mes <= 12

    # Consistencia contable básica
    assert round(nomina.total_devengado - nomina.total_deducir, 2) == pytest.approx(
        nomina.liquido_percibir, abs=0.02
    )
