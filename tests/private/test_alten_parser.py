"""Private ALTEN documentary regression: no economic selection or persistence."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest

from src.models.nomina import Nomina
from src.parsers.alten_parser import AltenParser
from src.services.ingestion_service import extract_pdf_document

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data/test/alten"
MANIFEST = ROOT / "data/private/alten-manifest.json"


@pytest.fixture(scope="module")
def oracle() -> dict[str, Any]:
    if not MANIFEST.is_file():
        pytest.fail("Missing private ALTEN manifest", pytrace=False)
    m = json.loads(MANIFEST.read_text())
    physical = m["physical_documents"]
    assert len(physical) == len({d["sha256_pdf"] for d in physical}) == 55
    assert sum(d["paginas"] for d in physical) == 84
    assert {p.name for p in CORPUS.iterdir() if p.suffix.lower() == ".pdf"} == {
        d["filename"] for d in physical
    }
    for d in physical:
        assert Path(d["filename"]).name == d["filename"]
        assert hashlib.sha256((CORPUS / d["filename"]).read_bytes()).hexdigest() == d["sha256_pdf"]
    assert len(m["payroll_versions"]) == 78
    assert len(m["period_groups"]) == 52
    return m


@pytest.fixture(scope="module")
def extracted(oracle):
    result = {}
    for entry in oracle["physical_documents"]:
        document = extract_pdf_document(CORPUS / entry["filename"])
        assert document.pages is not None and len(document.pages) == entry["paginas"]
        assert all(p.text.strip() and p.words and p.characters for p in document.pages)
        result[entry["filename"]] = document
    return result


@pytest.fixture(scope="module")
def parsed(oracle, extracted) -> dict[str, Nomina]:
    result = {}
    for e in oracle["payroll_versions"]:
        page = extracted[e["filename"]].pages[e["pagina"] - 1]
        result[e["version_key"]] = AltenParser().parse_extracted(page, "misleading.pdf")
    return result


def number(actual, expected, label):
    if expected is None:
        if actual is not None:
            pytest.fail(f"ALTEN fabricated {label}", pytrace=False)
    elif (
        actual is None
        or not math.isfinite(actual)
        or not math.isfinite(expected)
        or abs(actual - expected) > 1e-8
    ):
        pytest.fail(f"ALTEN mismatch: {label}", pytrace=False)


@pytest.mark.parametrize("index", range(78), ids=lambda i: f"version-{i + 1}")
def test_version(index, oracle, parsed, extracted):
    e = oracle["payroll_versions"][index]
    n = parsed[e["version_key"]]
    page = extracted[e["filename"]].pages[e["pagina"]-1]
    assert AltenParser.template(page.text) == e["familia_formato"]
    for field, key in [
        ("empresa", "empresa"),
        ("cif", "CIF"),
        ("fecha_inicio", "fecha_inicio"),
        ("fecha_fin", "fecha_fin"),
        ("anio", "anio"),
        ("mes", "mes"),
        ("fecha_alta", "fecha_alta"),
        ("categoria", "categoria_profesional_impresa"),
        ("grupo_cotizacion", "grupo_cotizacion"),
        ("categoria_convenio", "categoria_convenio"),
    ]:
        if getattr(n, field) != e[key]:
            pytest.fail(f"ALTEN identity/header mismatch: {field}", pytrace=False)
    assert n.tipo.value == e["tipo_documental"] == "NOMINA_ORDINARIA"
    assert AltenParser.period_key(n) == e["period_key"]
    for field, key in [
        ("total_devengado", "total_devengado"),
        ("total_deducir", "total_deducciones"),
        ("liquido_percibir", "liquido_percibir"),
        ("irpf_porcentaje", "porcentaje_irpf"),
        ("irpf_importe", "importe_irpf"),
        ("base_irpf", "base_irpf_partida"),
        ("base_irpf_pie", "base_irpf_pie"),
        ("base_sujeta_retencion_irpf", "base_sujeta_retencion_irpf"),
        ("base_irpf_especie", "base_irpf_especie"),
        ("base_ss_comunes", "base_ss_comunes"),
        ("base_at_ep", "base_at_ep"),
        ("prorrata_pagas_extra", "prorrata_pagas_extra"),
        ("pror_otros", "pror_otros"),
        ("descuento_seguridad_social", "seguridad_social_total"),
    ]:
        number(getattr(n, field), e[key], field)
    assert n.otras_deducciones is None
    assert len(n.conceptos) == len(e["conceptos"])
    for actual, expected in zip(n.conceptos, e["conceptos"], strict=True):
        assert actual.codigo == expected["codigo"]
        if actual.concepto != expected["descripcion"]:
            pytest.fail("ALTEN concept description mismatch", pytrace=False)
        assert (
            actual.columna
            == {"devengo": "devengos", "deduccion": "deducciones"}[expected["columna"]]
        )
        assert actual.atraso is expected["atraso"] is False
        assert actual.importe_texto == expected["importe_texto"]
        for field in ("importe", "base", "unidades", "precio", "porcentaje"):
            number(getattr(actual, field), expected[field], "concept " + field)
    assert Nomina.from_dict(json.loads(json.dumps(n.to_dict()))) == n


def test_quantitative_coverage(oracle, parsed, extracted):
    rows = [c for n in parsed.values() for c in n.conceptos]
    assert len(rows) == sum(len(v["conceptos"]) for v in oracle["payroll_versions"]) == 637
    assert len({c.codigo for c in rows}) == 16
    assert len({(c.codigo, c.concepto) for c in rows}) == 16
    assert Counter(
        AltenParser.template(extracted[e["filename"]].pages[e["pagina"] - 1].text)
        for e in oracle["payroll_versions"]
    ) == {"N1a": 11, "N1b": 37, "N2": 30}
    assert sum(n.pror_otros is not None for n in parsed.values()) == 12
    assert all(n.prorrata_pagas_extra is None for n in parsed.values())


def test_all_versions_retained(oracle, parsed):
    groups = defaultdict(list)
    for e in oracle["payroll_versions"]:
        groups[e["period_key"]].append(parsed[e["version_key"]])
    assert Counter(map(len, groups.values())) == {1: 27, 2: 24, 3: 1}
    for group in groups.values():
        assert len({n.id for n in group}) == 1  # Period ID, not a persistence key for versions.
        assert len({json.dumps(n.to_dict(), sort_keys=True) for n in group}) == len(group)
        for n in group:
            assert not {"current_version", "supersedes", "paid"} & n.to_dict().keys()


def test_multipage_contract(oracle, extracted, parsed):
    counts = []
    for d in oracle["physical_documents"]:
        if d["clasificacion"] != "NOMINAS" or d["paginas"] == 1:
            continue
        result = AltenParser().parse_pages(extracted[d["filename"]], "unrelated.pdf")
        expected = [
            parsed[e["version_key"]]
            for e in oracle["payroll_versions"]
            if e["filename"] == d["filename"]
        ]
        assert result == expected and len(result) == d["paginas"]
        counts.append(len(result))
        with pytest.raises(ValueError, match="page"):
            AltenParser().parse_extracted(extracted[d["filename"]])
    assert sorted(counts) == [2, 13, 14]


@pytest.mark.parametrize("index", range(3))
def test_certificates_rejected(index, oracle, extracted):
    e = oracle["certificates"][index]
    assert not e["processable_monthly_parser"]
    for page in extracted[e["filename"]].pages:
        with pytest.raises(ValueError):
            AltenParser().parse_extracted(page)
        with pytest.raises(ValueError):
            AltenParser().parse(page.text)


def test_documentary_discrepancies_are_not_corrected(oracle, parsed):
    entries = [
        e
        for e in oracle["payroll_versions"]
        if e["validacion_importes"]["diferencia_dev_impreso_menos_filas"]
        or e["validacion_importes"]["diferencia_ded_impreso_menos_filas"]
    ]
    assert len(entries) == 5
    for e in entries:
        n = parsed[e["version_key"]]
        for col, field, key in [
            ("devengos", "total_devengado", "diferencia_dev_impreso_menos_filas"),
            ("deducciones", "total_deducir", "diferencia_ded_impreso_menos_filas"),
        ]:
            delta = round(
                getattr(n, field) - sum(c.importe for c in n.conceptos if c.columna == col), 2
            )
            number(delta, e["validacion_importes"][key], key)
