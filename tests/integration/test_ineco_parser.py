"""Private oracle regression; never copy audited values into this versioned file.

The independently audited manifest lives in ignored data/private/. A missing or
changed PDF, missing manifest or new unclassified document requires review.
Only --run-private collects this module. Scanned documents never enter the parser.
"""

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from src.parsers.ineco_parser import InecoParser
from src.parsers.parser_factory import ParserFactory
from src.services.ingestion_service import NoExtractableTextError, parse_nomina_pdf

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data/test/ineco"
MANIFEST_PATH = ROOT / "data/private/ineco-manifest.json"
if not MANIFEST_PATH.is_file():
    pytest.fail("Missing private INECO manifest: data/private/ineco-manifest.json", pytrace=False)
MANIFEST = json.loads(MANIFEST_PATH.read_text())
TEXTUAL = MANIFEST["textual"]
SCANNED = MANIFEST["scanned"]


def _check_inventory() -> None:
    entries = TEXTUAL + SCANNED
    names = [entry["filename"] for entry in entries]
    assert len(TEXTUAL) == 60 and len(SCANNED) == 1, "Review INECO corpus counts"
    assert len(names) == len(set(names)), "Duplicate INECO filename"
    assert all(Path(name).name == name and name.lower().endswith(".pdf") for name in names)
    observed = {p.name for p in CORPUS.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}
    assert observed == set(names), "Missing or unclassified INECO PDF: review manifest"
    for entry in entries:
        digest = hashlib.sha256((CORPUS / entry["filename"]).read_bytes()).hexdigest()
        assert digest == entry["sha256_pdf"], "INECO PDF changed since oracle audit"
    keys = [entry["clave_documental"] for entry in TEXTUAL]
    assert len(keys) == len(set(keys)), "Oracle documentary key collision"


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    _check_inventory()
    result = {}
    for entry in TEXTUAL + SCANNED:
        with pdfplumber.open(CORPUS / entry["filename"]) as pdf:
            assert len(pdf.pages) == entry["paginas"], "INECO page count changed"
            result[entry["filename"]] = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return result


def test_ineco_inventory() -> None:
    _check_inventory()


@pytest.mark.parametrize("expected", TEXTUAL, ids=[f"textual-{i:02d}" for i in range(1, 61)])
def test_ineco_fundamentals(expected: dict[str, Any], texts: dict[str, str]) -> None:
    text = texts[expected["filename"]]
    assert expected["procesable_parser_textual"] and text.strip()
    parser = ParserFactory().obtener_parser(text)  # No filename-assisted identification.
    assert isinstance(parser, InecoParser)
    doc = parser.parse(text)
    for field in ("empresa", "cif", "fecha_inicio", "fecha_fin", "anio", "mes"):
        if getattr(doc, field) != expected[field]:
            pytest.fail(f"INECO identity/period mismatch: field={field}", pytrace=False)
    assert doc.periodo == f"{expected['anio']:04d}-{expected['mes']:02d}"
    assert doc.tipo.value == expected["tipo_documental"]
    amount_fields = {
        "total_devengado": "total_devengado", "total_deducir": "total_deducciones",
        "liquido_percibir": "liquido_percibir", "irpf_porcentaje": "porcentaje_irpf",
        "irpf_importe": "importe_irpf", "base_irpf": "base_irpf",
    }
    for field, oracle_key in amount_fields.items():
        actual, value = getattr(doc, field), expected[oracle_key]
        if value is None:
            if actual is not None:
                pytest.fail(f"INECO fabricated absent value: field={field}", pytrace=False)
        elif (actual is None or not math.isfinite(actual) or not math.isfinite(value)
              or abs(actual - value) > 0.005):
            pytest.fail(f"INECO amount mismatch: field={field}", pytrace=False)
    assert doc.descuento_seguridad_social is None
    assert doc.otras_deducciones is None


def test_ineco_ids_unique_and_partial_periods_preserved(texts: dict[str, str]) -> None:
    docs = [InecoParser().parse(texts[entry["filename"]]) for entry in TEXTUAL]
    assert len({doc.id for doc in docs}) == 60, "INECO ID collision"
    for doc, entry in zip(docs, TEXTUAL, strict=True):
        assert doc.id == InecoParser().parse(texts[entry["filename"]], "renamed.pdf").id
    partial_months = {(doc.anio, doc.mes) for doc in docs
                      if sum((d.anio, d.mes) == (doc.anio, doc.mes) for d in docs) > 1}
    assert partial_months, "Expected the independently audited split payroll periods"
    for year, month in partial_months:
        pair = sorted((d for d in docs if (d.anio, d.mes) == (year, month)),
                      key=lambda d: d.fecha_inicio or "")
        assert len(pair) == 2
        assert pair[0].fecha_fin is not None and pair[1].fecha_inicio is not None
        assert pair[0].fecha_fin < pair[1].fecha_inicio


def test_ineco_scanned_dossier_is_not_textually_processable(texts: dict[str, str]) -> None:
    entry = SCANNED[0]
    assert entry["clasificacion"] == "escaneado_mixto"
    assert not entry["procesable_parser_textual"]
    assert not texts[entry["filename"]].strip(), "Scanned dossier now has text: review oracle"
    with pytest.raises(NoExtractableTextError):
        parse_nomina_pdf(CORPUS / entry["filename"])


@pytest.mark.parametrize("expected", TEXTUAL, ids=[f"concepts-{i:02d}" for i in range(1, 61)])
def test_ineco_audited_concepts(expected: dict[str, Any], texts: dict[str, str]) -> None:
    from collections import Counter

    doc = InecoParser().parse(texts[expected["filename"]])
    special_categories = {
        "antiguedad", "paga_extra_incluida", "atrasos", "beneficios", "regularizaciones",
        "prestaciones", "seguro_de_vida", "ingreso_a_cuenta", "vacaciones",
    }

    def number(value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            pytest.fail("Non-finite INECO concept oracle/result", pytrace=False)
        return round(value, 2)

    def label(value: str) -> str:
        import unicodedata

        plain = "".join(c for c in unicodedata.normalize("NFD", value)
                        if not unicodedata.combining(c))
        return " ".join(plain.lower().split())

    # Multisets preserve repeated codes, including identical insurance deductions.
    actual_special = Counter((c.codigo, label(c.concepto), c.categoria, c.columna,
                              c.atraso, number(c.importe))
                             for c in doc.conceptos if c.categoria in special_categories)
    expected_special = Counter((c["codigo"], label(c["concepto"]), c["categoria"], c["columna"],
                                c["atraso"], number(c["importe"]))
                               for c in expected["conceptos_especiales"])
    if actual_special != expected_special:
        pytest.fail("INECO special concepts differ from private oracle", pytrace=False)
    actual_ss = Counter((c.codigo, label(c.concepto), number(c.importe), number(c.porcentaje))
                        for c in doc.conceptos if c.categoria == "cotizacion_trabajador")
    expected_ss = Counter((c["codigo"], label(c["concepto"]), number(c["importe"]), number(c["porcentaje"]))
                          for c in expected["cotizaciones_seguridad_social"])
    if actual_ss != expected_ss:
        pytest.fail("INECO employee contributions differ from private oracle", pytrace=False)
    for entry in expected["conceptos_especiales"]:
        values = entry.get("valores_fila_extraidos")
        if values and entry["categoria"] in {"prestaciones", "vacaciones"}:
            units = float(values[0].replace(".", "").replace(",", "."))
            price = float(values[1].replace(".", "").replace(",", ".")) if len(values) == 3 else None
            matches = [c for c in doc.conceptos if c.codigo == entry["codigo"]
                       and label(c.concepto) == label(entry["concepto"])
                       and number(c.importe) == number(entry["importe"])]
            if not any(number(c.unidades) == number(units) and number(c.precio) == number(price)
                       for c in matches):
                pytest.fail("INECO printed units/price mismatch", pytrace=False)
