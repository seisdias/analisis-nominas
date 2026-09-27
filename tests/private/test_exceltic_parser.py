"""Private Exceltic oracle: no corpus values or personal data in this module."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from src.models.nomina import Nomina
from src.parsers.exceltic_parser import ExcelticParser
from src.parsers.parser_factory import ParserFactory

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data/test/exceltic"
MANIFEST_PATH = ROOT / "data/private/exceltic-manifest.json"
if not MANIFEST_PATH.is_file():
    pytest.fail("Missing private Exceltic manifest", pytrace=False)
MANIFEST = json.loads(MANIFEST_PATH.read_text())
TEXTUAL = MANIFEST["textual"]


def _inventory() -> None:
    assert len(TEXTUAL) == 8 and not MANIFEST["scanned"], "Review Exceltic corpus"
    names = [e["filename"] for e in TEXTUAL]
    assert len(names) == len(set(names))
    assert all(Path(n).name == n and n.lower().endswith(".pdf") for n in names)
    assert CORPUS.is_dir(), "Missing private Exceltic corpus"
    actual = {p.name for p in CORPUS.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"}
    assert actual == set(names), "Missing or unclassified Exceltic PDF"
    for entry in TEXTUAL:
        digest = hashlib.sha256((CORPUS / entry["filename"]).read_bytes()).hexdigest()
        assert digest == entry["sha256_pdf"], "Exceltic PDF changed since audit"
    assert sorted(Counter(e["clave_documental"] for e in TEXTUAL).values()) == [1] * 6 + [2]
    assert len(MANIFEST["grupos_duplicados"]) == 1


@pytest.fixture(scope="module")
def documents() -> dict[str, Nomina]:
    _inventory()
    result = {}
    for entry in TEXTUAL:
        with pdfplumber.open(CORPUS / entry["filename"]) as pdf:
            assert len(pdf.pages) == entry["paginas"]
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        assert text.strip() and entry["texto_extraible"] and entry["procesable_parser_textual"]
        parser = ParserFactory().obtener_parser(text)
        assert isinstance(parser, ExcelticParser)
        doc = parser.parse(text, entry["filename"])
        assert doc.to_dict() == parser.parse(text, "unrelated.pdf").to_dict()
        result[entry["filename"]] = doc
    return result


def _same_number(actual: float | None, expected: float | None, field: str) -> None:
    if expected is None:
        if actual is not None:
            pytest.fail(f"Fabricated Exceltic value: {field}", pytrace=False)
    elif (actual is None or not math.isfinite(actual) or not math.isfinite(expected)
          or abs(actual - expected) > 1e-8):
        pytest.fail(f"Exceltic amount mismatch: {field}", pytrace=False)


def test_exceltic_inventory():
    _inventory()


@pytest.mark.parametrize("expected", TEXTUAL, ids=[f"textual-{i}" for i in range(1, 9)])
def test_exceltic_private_document(expected: dict[str, Any], documents: dict[str, Nomina]):
    doc = documents[expected["filename"]]
    for field in ("empresa", "cif", "fecha_inicio", "fecha_fin", "anio", "mes"):
        if getattr(doc, field) != expected[field]:
            pytest.fail(f"Exceltic identity/period mismatch: {field}", pytrace=False)
    assert doc.periodo == f"{expected['anio']:04d}-{expected['mes']:02d}"
    assert doc.tipo.value.lower() == expected["tipo_documental"]
    assert doc.fecha_inicio is not None and doc.fecha_fin is not None
    classification = ("nomina_ordinaria_parcial" if doc.fecha_inicio[-2:] != "01"
                      else "nomina_ordinaria")
    assert classification == expected["clasificacion_funcional"]
    key = f"{doc.cif}|{doc.fecha_inicio}|{doc.fecha_fin}|{doc.tipo.value.lower()}"
    assert key == expected["clave_documental"]
    for actual, oracle in {
        "total_devengado": "total_devengado", "total_deducir": "total_deducciones",
        "liquido_percibir": "liquido_percibir", "irpf_porcentaje": "porcentaje_irpf",
        "irpf_importe": "importe_irpf", "base_irpf": "base_irpf",
        "base_ss_comunes": "base_ss_comunes", "base_at_ep": "base_at_ep",
        "prorrata_pagas_extra": "prorrata_pagas_extra",
        "descuento_seguridad_social": "seguridad_social",
    }.items():
        _same_number(getattr(doc, actual), expected[oracle], actual)
    assert doc.otras_deducciones is None
    # Ordered occurrences preserve two columns and repeated 1/2 indicators.
    assert len(doc.conceptos) == len(expected["conceptos"])
    for actual_concept, oracle_concept in zip(doc.conceptos, expected["conceptos"], strict=True):
        for actual, oracle in {
            "concepto": "descripcion", "categoria": "categoria_funcional",
            "codigo": "indicador_cotizacion_impreso",
        }.items():
            if getattr(actual_concept, actual) != oracle_concept[oracle]:
                pytest.fail(f"Exceltic concept mismatch: {actual}", pytrace=False)
        assert actual_concept.columna == {
            "devengo": "devengos", "deduccion": "deducciones",
        }[oracle_concept["columna"]]
        for field in ("importe", "unidades", "precio", "porcentaje"):
            _same_number(getattr(actual_concept, field), oracle_concept[field], field)
        if actual_concept.importe_texto != oracle_concept["representacion_impresa"].split()[-1]:
            pytest.fail("Exceltic printed amount notation mismatch", pytrace=False)
    by_ref = dict(zip((c["id_partida"] for c in expected["conceptos"]), doc.conceptos, strict=True))
    for contribution in expected["cotizaciones_seguridad_social"]:
        assert contribution["repeticion_visual"] and not contribution["deduccion_adicional"]
        c = by_ref[contribution["partida_ref"]]
        assert c.columna == "deducciones"
        _same_number(c.importe, contribution["importe_impreso"], "contribution")
        _same_number(c.porcentaje, contribution["porcentaje_impreso"], "contribution rate")
    assert Nomina.from_dict(doc.to_dict()) == doc


def test_exceltic_economic_identity_and_duplicate(documents: dict[str, Nomina]):
    groups: dict[str, list[Nomina]] = defaultdict(list)
    for entry in TEXTUAL:
        groups[entry["clave_documental"]].append(documents[entry["filename"]])
    assert len(groups) == 7
    assert len({doc.id for doc in documents.values()}) == 7
    for group in groups.values():
        assert all(doc.to_dict() == group[0].to_dict() for doc in group)
    duplicate = MANIFEST["grupos_duplicados"][0]
    assert duplicate["documentos_economicos"] == 1
    names = duplicate["archivos"]
    assert len(names) == 2
    assert {e["filename"] for e in TEXTUAL
            if e["grupo_duplicado"] == duplicate["clave_documental"]} == set(names)
    assert all(e["clave_documental"] == duplicate["clave_documental"]
               for e in TEXTUAL if e["filename"] in names)
    assert documents[names[0]].to_dict() == documents[names[1]].to_dict()
