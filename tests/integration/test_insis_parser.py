"""Private INSIS4 regression, explicitly enabled with --run-private.

Keep the audited inventory/amounts in data/private/insis4-manifest.json (ignored).
The manifest has 'textual' and 'scanned' lists; every entry has a 'filename'.
Textual entries contain year/month/type and audited Nomina amounts. Scanned
entries contain only type/status. Never regenerate expectations from the parser.
An absent manifest, missing document or unclassified PDF is an explicit failure.
"""

import json
import math
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from src.models.documento_laboral import TipoDocumento
from src.parsers.insis_parser import InsisParser

ROOT = Path(__file__).resolve().parents[2]
INSIS_DIR = ROOT / "data/test/insis4"
MANIFEST_PATH = ROOT / "data/private/insis4-manifest.json"
if not MANIFEST_PATH.is_file():
    pytest.fail("Missing private INSIS4 manifest: data/private/insis4-manifest.json", pytrace=False)
MANIFEST = json.loads(MANIFEST_PATH.read_text())
TEXTUAL = MANIFEST["textual"]
SCANNED = MANIFEST["scanned"]


def _check_inventory() -> None:
    names = [entry["filename"] for entry in TEXTUAL + SCANNED]
    assert len(TEXTUAL) == 23 and len(SCANNED) == 2, "Review INSIS4 inventory counts"
    assert len(names) == len(set(names)), "Duplicate INSIS4 manifest filename"
    assert all(Path(name).name == name and name.lower().endswith(".pdf") for name in names)
    observed = {path.name for path in INSIS_DIR.iterdir()
                if path.is_file() and path.suffix.lower() == ".pdf"}
    assert set(names) == observed, (
        f"INSIS4 inventory mismatch: missing={sorted(set(names) - observed)}, "
        f"unclassified={sorted(observed - set(names))}"
    )


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    _check_inventory()
    result = {}
    for entry in TEXTUAL + SCANNED:
        name = entry["filename"]
        with pdfplumber.open(INSIS_DIR / name) as pdf:
            result[name] = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return result


def test_insis_inventory() -> None:
    _check_inventory()


@pytest.mark.parametrize("expected", TEXTUAL, ids=[entry["filename"] for entry in TEXTUAL])
def test_parse_insis_pdf(expected: dict[str, Any], texts: dict[str, str]) -> None:
    name = expected["filename"]
    assert texts[name].strip(), "Expected textual payroll; scan must be classified separately"
    doc = InsisParser().parse(texts[name], filename=name)
    assert (doc.anio, doc.mes, doc.tipo.value) == (expected["anio"], expected["mes"], expected["tipo"])
    assert doc.periodo == f"{expected['anio']:04d}-{expected['mes']:02d}"
    assert doc.id == f"insis4-{doc.periodo}-{expected['tipo'].lower()}"
    assert doc.empresa == "INTELIGENCIA SISTEMATICA 4, S.L."
    assert doc.cif == "B84225283"
    assert doc.observaciones == f"Procesado desde {name}"
    required = {"total_devengado", "total_deducir", "liquido_percibir",
                "irpf_porcentaje", "irpf_importe", "base_irpf", "salario_base",
                "plus_convenio", "complementos", "otras_deducciones",
                "descuento_seguridad_social", "base_ss_comunes", "prorrata_pagas_extra"}
    assert required <= expected.keys(), "Private manifest is missing audited fields"
    for field in required:
        # No real amounts or complete extracted text in assertion messages.
        actual_value = getattr(doc, field)
        expected_value = expected[field]
        if not math.isfinite(actual_value) or not math.isfinite(expected_value):
            pytest.fail(f"Non-finite INSIS4 regression value: {name}, field={field}", pytrace=False)
        if abs(actual_value - expected_value) > 0.005:
            pytest.fail(f"INSIS4 regression mismatch: {name}, field={field}", pytrace=False)


@pytest.mark.parametrize("entry", SCANNED, ids=[entry["filename"] for entry in SCANNED])
def test_insis_scanned_documents_are_pending(entry: dict[str, str], texts: dict[str, str]) -> None:
    assert entry["status"] == "scanned_pending"
    assert entry["tipo"] in {"NOMINA_ORDINARIA", "FINIQUITO"}
    assert not texts[entry["filename"]].strip(), "Scan now has text: review its classification"
    # Intentionally no InsisParser call and no OCR.


def test_insis_ids_and_extra_coexistence(texts: dict[str, str]) -> None:
    docs = [InsisParser().parse(texts[entry["filename"]]) for entry in TEXTUAL]
    assert len({doc.id for doc in docs}) == len(docs), "INSIS4 ID collision"
    extras = [doc for doc in docs if doc.tipo == TipoDocumento.PAGA_EXTRA]
    assert len(extras) == 3
    for extra in extras:
        assert any(doc.periodo == extra.periodo and doc.tipo == TipoDocumento.NOMINA_ORDINARIA
                   and doc.id != extra.id for doc in docs)
