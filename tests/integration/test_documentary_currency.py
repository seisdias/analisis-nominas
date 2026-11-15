"""Real PDF bytes, synthetic inspector evidence; no private document fixtures."""

from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.canonical.facts import FactPageReference
from src.canonical_inspection import CanonicalInspector
from src.document_concepts import DocumentConcepts, project_extraction
from src.documentary_currency import INSIS_REVISION, attach_currency
from tests.unit.test_document_concepts import DOC, EXT, VER, fact


def pdf_bytes():
    text = r"LIQUIDO TOTAL A PERCIBIR \(A-B\) EUROS 1.234,56"
    stream = f"BT /F1 10 Tf 40 780 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return data + f"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "changed_pdf",
        "wrong_page",
        "wrong_version",
        "missing_source",
        "multi",
        "unsupported_fact",
        "invalid_pdf",
    ],
)
def test_pdf_currency_is_bound_to_hash_fact_page_and_version(tmp_path, case):
    path = tmp_path / "synthetic.pdf"
    data = pdf_bytes()
    path.write_bytes(data)
    f = fact("nomina.liquido_percibir", 123456)
    e = project_extraction(
        DOC,
        VER,
        EXT,
        (f,),
        pages={f.fact_id: (1,)},
        extractor_name="InsisParser",
        extractor_revision=INSIS_REVISION,
    )
    sources = {DOC: DocumentConcepts(DOC, (VER,), (e,))}
    inspector = Mock(spec=CanonicalInspector)
    inspector.explain.return_value = dict(
        certification={"status": "certified"},
        observation=SimpleNamespace(value=f.value),
        supporting_facts=[{"fact": f}],
    )
    inspector.fact_pages.return_value = (FactPageReference(f.fact_id, VER, 1),)
    inspector.document.return_value = {
        "versions": [
            dict(
                pages=[SimpleNamespace(page_number=1)],
                source_file=SimpleNamespace(sha256=sha256(data).hexdigest()),
                locations=[dict(corpus_id="corpus", relative_path="synthetic.pdf")],
            )
        ]
    }
    rows: list[dict[str, Any]] = [
        dict(
            document_id=DOC,
            series="Neto",
            observation_id="obs",
            source_version_ids=(VER,),
            value=dict(status="certified", amount=f.value.value, currency=None),
        )
    ]
    if case == "invalid_pdf":
        data = b"not a PDF"
        path.write_bytes(data)
        inspector.document.return_value["versions"][0]["source_file"].sha256 = sha256(
            data
        ).hexdigest()
    if case == "changed_pdf":
        path.write_bytes(data + b"changed")
    if case == "wrong_page":
        inspector.fact_pages.return_value = (FactPageReference(f.fact_id, VER, 2),)
    if case == "wrong_version":
        rows[0]["source_version_ids"] = ("other",)
    if case == "missing_source":
        path.unlink()
    if case == "multi":
        sources[DOC] = replace(sources[DOC], version_ids=(VER, "other"))
    if case == "unsupported_fact":
        inspector.explain.return_value["supporting_facts"] = []
    attach_currency(inspector, rows, sources, {"corpus": tmp_path})
    assert ("currency_evidence" in rows[0]) == (case == "valid")
    assert rows[0]["value"]["currency"] is None
