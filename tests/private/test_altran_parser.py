"""Private fundamental and concept regression; values stay in data/private."""
import calendar
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from src.models.nomina import Nomina
from src.parsers.altran_parser import AltranParser
from src.services.ingestion_service import extract_pdf_document

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data/test/altran"
MANIFEST = ROOT / "data/private/altran-manifest.json"


@pytest.fixture(scope="module")
def oracle(request: pytest.FixtureRequest) -> dict[str, Any]:
    if not request.config.getoption("--run-private"):
        pytest.skip("Requires --run-private and the private Altran corpus")
    if not MANIFEST.is_file():
        pytest.fail("Missing private Altran manifest", pytrace=False)
    result = json.loads(MANIFEST.read_text())
    entries = result["payrolls"] + result["certificates"] + result["scanned"]
    assert (len(result["payrolls"]), len(result["certificates"]), len(result["scanned"])) == (73, 4, 1)
    names = [e["filename"] for e in entries]
    assert len(names) == len(set(names)) == 78
    assert all(Path(n).name == n and n.lower().endswith(".pdf") for n in names)
    assert {p.name for p in CORPUS.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"} == set(names)
    for e in entries:
        assert hashlib.sha256((CORPUS / e["filename"]).read_bytes()).hexdigest() == e["sha256_pdf"]
    assert sorted(Counter(e["clave_documental"] for e in result["payrolls"]).values()) == [1] * 69 + [2, 2]
    assert len(result["duplicate_groups"]) == 2
    return result


def _text(entry: dict[str, Any]) -> str:
    with pdfplumber.open(CORPUS / entry["filename"]) as pdf:
        assert len(pdf.pages) == entry["paginas"]
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


@pytest.fixture(scope="module")
def documents(oracle: dict[str, Any]) -> dict[str, Nomina]:
    result = {}
    for e in oracle["payrolls"]:
        extracted = extract_pdf_document(CORPUS / e["filename"])
        text = extracted.text
        assert extracted.words
        assert len({w.page for w in extracted.words}) == e["paginas"]
        assert text.strip() and e["text_extractable"] and e["processable_text_parser"]
        doc = AltranParser().parse_extracted(extracted, e["filename"])
        assert replace(doc, conceptos=[]).to_dict() == AltranParser().parse(text, "unrelated.pdf").to_dict()
        assert doc == AltranParser().parse_extracted(extracted, "unrelated.pdf")
        result[e["filename"]] = doc
    return result


def _number(actual: float | None, expected: float | None, field: str) -> None:
    if expected is None:
        if actual is not None:
            pytest.fail(f"Fabricated Altran field: {field}", pytrace=False)
    elif (actual is None or not math.isfinite(actual) or not math.isfinite(expected)
          or abs(actual - expected) > 1e-8):
        pytest.fail(f"Altran field mismatch: {field}", pytrace=False)


@pytest.mark.parametrize("index", range(73), ids=lambda i: f"payroll-{i + 1}")
def test_payroll(index: int, oracle: dict[str, Any], documents: dict[str, Nomina]):
    e = oracle["payrolls"][index]
    doc = documents[e["filename"]]
    for key in ("empresa", "cif", "fecha_inicio", "fecha_fin", "anio", "mes"):
        if getattr(doc, key) != e[key]:
            pytest.fail(f"Altran identity mismatch: {key}", pytrace=False)
    assert doc.tipo.value == e["tipo_documental"] == "NOMINA_ORDINARIA"
    assert doc.periodo == f"{e['anio']:04d}-{e['mes']:02d}"
    identifier = doc.periodo + "-ALTRAN"
    if int(e["fecha_inicio"][-2:]) != 1 or int(e["fecha_fin"][-2:]) != calendar.monthrange(e["anio"], e["mes"])[1]:
        identifier += f"-{e['fecha_inicio']}_{e['fecha_fin']}"
    assert doc.id == identifier
    assert f"{doc.cif}|{doc.fecha_inicio}|{doc.fecha_fin}|{doc.tipo.value}" == e["clave_documental"]
    for actual, expected in {
        "total_devengado": "total_devengado", "total_deducir": "total_deducciones",
        "liquido_percibir": "liquido_percibir", "base_irpf": "base_irpf_ordinaria",
        "irpf_porcentaje": "porcentaje_irpf_ordinario", "irpf_importe": "importe_irpf_ordinario",
        "base_ss_comunes": "base_ss_comunes", "base_at_ep": "base_at_ep",
        "prorrata_pagas_extra": "prorrata_pagas_extra",
        "descuento_seguridad_social": "seguridad_social_total",
    }.items():
        _number(getattr(doc, actual), e[expected], actual)
    assert doc.otras_deducciones is None
    # Only the existing ordinary scalar fields are part of phase 2A.
    for code, field in (("R1A", "salario_base"), ("R1B", "plus_convenio"), ("R1R", "complementos")):
        rows = [c for c in e["conceptos"] if c["codigo"] == code and not c["es_regularizacion"]]
        assert len(rows) == 1 and rows[0]["columna"] == "devengo"
        _number(getattr(doc, field), rows[0]["importe"], field)

    # Every oracle row remains independent and in document order.
    assert len(doc.conceptos) == len(e["conceptos"])
    fiscal = {"F74", "FE4", "700", "705", "707"}
    for concept, expected in zip(doc.conceptos, e["conceptos"], strict=True):
        for field, key in (("codigo", "codigo"), ("concepto", "descripcion"),
                           ("categoria", "categoria_funcional"), ("atraso", "es_regularizacion")):
            if getattr(concept, field) != expected[key]:
                pytest.fail(f"Altran concept mismatch: {field}", pytrace=False)
        assert concept.columna == {"devengo": "devengos", "deduccion": "deducciones"}[expected["columna"]]
        tax = expected["codigo"] in fiscal
        for field, value in {
            "importe": expected["importe"],
            "base": expected["cantidad_base"] if tax else None,
            "unidades": None if tax else expected["cantidad_base"],
            "porcentaje": expected["precio_porcentaje"] if tax else None,
            "precio": None if tax else expected["precio_porcentaje"],
        }.items():
            _number(getattr(concept, field), value, field)
        assert concept.importe_texto == expected["representacion_impresa"][concept.columna]
    f74 = [c for c in doc.conceptos if c.codigo == "F74" and not c.atraso]
    assert len(f74) == 1
    for field, scalar in (("base", "base_irpf"), ("porcentaje", "irpf_porcentaje"),
                          ("importe", "irpf_importe")):
        _number(getattr(f74[0], field), getattr(doc, scalar), field)
    assert Nomina.from_dict(doc.to_dict()) == doc



def test_duplicates(oracle: dict[str, Any], documents: dict[str, Nomina]):
    groups: dict[str, list[Nomina]] = defaultdict(list)
    for e in oracle["payrolls"]:
        groups[e["clave_documental"]].append(documents[e["filename"]])
    assert len(groups) == len({d.id for d in documents.values()}) == 71
    for group in groups.values():
        assert all(d.to_dict() == group[0].to_dict() for d in group)
    for duplicate in oracle["duplicate_groups"]:
        names = duplicate["filenames"]
        assert len(names) == 2
        assert {e["filename"] for e in oracle["payrolls"]
                if e["clave_documental"] == duplicate["clave_documental"]} == set(names)
        assert documents[names[0]].to_dict() == documents[names[1]].to_dict()


@pytest.mark.parametrize("index", range(4), ids=lambda i: f"certificate-{i + 1}")
def test_certificate_rejected(index: int, oracle: dict[str, Any]):
    e = oracle["certificates"][index]
    text = _text(e)
    assert text.strip() and not e["processable_text_parser"]
    with pytest.raises(ValueError):
        AltranParser().parse(text, e["filename"])


def test_scanned_excluded(oracle: dict[str, Any]):
    e = oracle["scanned"][0]
    assert not e["text_extractable"] and not e["processable_text_parser"]
    assert not _text(e).strip()
    # No OCR and no attempt to parse the scanned document.


@pytest.mark.parametrize("family,column,code", [
    ("N1", "devengo", "700"), ("N1", "deduccion", "U3C"),
    ("N2", "devengo", "U3D"), ("N2", "deduccion", "700"),
])
def test_real_atr_column_evidence(family: str, column: str, code: str, oracle: dict[str, Any]):
    # Oracle selects representative evidence, never supplies the classification.
    entry = next(e for e in oracle["payrolls"] if e["familia_formato"] == family
                 and any(c["codigo"] == code and c["es_regularizacion"]
                         and c["columna"] == column for c in e["conceptos"]))
    extracted = extract_pdf_document(CORPUS / entry["filename"])
    assert extracted.words
    candidates = []
    for marker in extracted.words:
        if marker.text != "ATR.":
            continue
        row = sorted((w for w in extracted.words if w.page == marker.page
                      and abs(w.top - marker.top) < (marker.bottom - marker.top) / 2),
                     key=lambda w: w.x0)
        if len(row) > 2 and row[1].text == code:
            candidates.append(row[-1])
    assert len(candidates) == 1
    assert AltranParser.concept_column(extracted, candidates[0]) == {
        "devengo": "devengos", "deduccion": "deducciones",
    }[column]


def test_exhaustive_quantities(oracle: dict[str, Any], documents: dict[str, Nomina]):
    expected = [c for e in oracle["payrolls"] for c in e["conceptos"]]
    actual = [c for doc in documents.values() for c in doc.conceptos]
    assert len(actual) == len(expected) == 1145
    assert sum(c.atraso for c in actual) == sum(c["es_regularizacion"] for c in expected) == 32
    assert {c.codigo for c in actual} == {c["codigo"] for c in expected}
    assert len({c.codigo for c in actual}) == 33
    assert {(c.codigo, c.concepto) for c in actual} == {
        (c["codigo"], c["descripcion"]) for c in expected
    }
    assert len({(c.codigo, c.concepto) for c in actual}) == 34
    assert Counter((c.codigo, c.atraso, c.columna) for c in actual) == Counter(
        (c["codigo"], c["es_regularizacion"],
         {"devengo": "devengos", "deduccion": "deducciones"}[c["columna"]]) for c in expected
    )
    assert all(any(c.codigo == "FE4" for c in documents[e["filename"]].conceptos)
               == any(c["codigo"] == "FE4" for c in e["conceptos"])
               for e in oracle["payrolls"])
    print("ALTRAN: PDFs 73/73; filas 1145/1145; ATR 32/32; códigos 33/33; combinaciones 34/34")


@pytest.mark.parametrize("year,month,codes", [
    (2016, 5, {"R3A", "R3C", "U2P", "U3P"}),
    (2016, 6, {"U3C", "U3D"}),
    (2016, 10, {"U2M", "U3M"}),
    (2017, 5, {"A29", "R1W"}),
    (2017, 11, {"R1A"}),
    (2017, 12, {"R1A"}),
    (2018, 5, {"R2R"}),
    (2019, 5, {"A29", "S75", "R1W", "R1X"}),
    (2020, 4, {"R3Z"}),
    (2021, 4, {"R3Z", "R3H"}),
    (2021, 6, {"R3Q", "707"}),
    (2021, 10, {"R2T", "R3Q", "707"}),
    (2021, 12, {"R5S"}),
    (2022, 1, {"R1A"}),
])
def test_special_case_coverage(year, month, codes, oracle, documents):
    entry = next(e for e in oracle["payrolls"] if (e["anio"], e["mes"]) == (year, month))
    doc = documents[entry["filename"]]
    assert codes <= {c.codigo for c in doc.conceptos}
    # Values stay in the oracle and are exhaustively compared by test_payroll.
    assert doc.prorrata_pagas_extra == entry["prorrata_pagas_extra"]
    assert (doc.fecha_inicio, doc.fecha_fin) == (entry["fecha_inicio"], entry["fecha_fin"])
