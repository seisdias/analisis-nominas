from pathlib import Path

import pdfplumber
import pytest

from src.parsers.ineco_parser import InecoParser

# Buscar rutas posibles
INECO_DIR = Path("data/testdata/ineco")
if not INECO_DIR.exists():
    INECO_DIR = Path("data/testdata/ineco_parser")

INECO_FILES = sorted(list(INECO_DIR.glob("*.pdf"))) if INECO_DIR.exists() else []


@pytest.mark.skipif(len(INECO_FILES) == 0, reason="No se encontraron PDFs de prueba reales en data/testdata/")
@pytest.mark.parametrize("pdf_path", INECO_FILES)
def test_parse_ineco_pdf_real(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

    parser = InecoParser()
    nomina = parser.parse(text, filename=pdf_path.name)

    assert nomina.empresa == "Ingeniería y Economía del Transporte S.M.E. M.P. S.A."
    assert nomina.cif == "A28220168"
    assert nomina.total_devengado > 0
    assert nomina.liquido_percibir > 0
    assert nomina.anio >= 2000
    assert 1 <= nomina.mes <= 12
