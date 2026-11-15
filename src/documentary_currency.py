"""Read-only currency evidence for the reviewed INSIS4 net-total label.

No payroll parsing, canonical enrichment or document-wide currency inference.
The build manifest locates files only; stored hashes and fact provenance bind them.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from src.canonical.certification import CertificationRequirements
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.canonical_inspection import CanonicalInspector
from src.document_concepts import DocumentConcepts

INSIS_REVISION = "4366ff51169e02bb417b98fe13f8b1ae7eca7e1bf678ada355a78796e33466d9"
CONTRACT = "insis-explicit-net-currency/c4.4b-v1"
_NET = re.compile(r"LIQUIDOTOTALAPERCIBIR\(A-B\)EUROS(-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})$")


@dataclass(frozen=True)
class CurrencyEvidence:
    document_id: str
    version_id: str
    extraction_id: str
    observation_id: str
    fact_id: str
    file_sha256: str
    page: int
    text_sha256: str
    amount: ExactDecimal
    currency: CurrencyCode
    scope: str = "documentary_net"
    contract: str = CONTRACT


def attest_net(
    *,
    document_id: str,
    version_id: str,
    extraction_id: str,
    observation_id: str,
    fact_id: str,
    file_sha256: str,
    parser: str,
    revision: str,
    page: int,
    value: CanonicalValue,
    text: str,
) -> CurrencyEvidence | None:
    if (
        parser != "InsisParser"
        or revision != INSIS_REVISION
        or page != 1
        or value.state != ValueState.PRESENT
        or not isinstance(value.value, ExactDecimal)
        or value.currency not in (None, CurrencyCode("EUR"))
    ):
        return None
    compact = ["".join(line.upper().split()) for line in text.splitlines()]
    # Conflicting/dual-unit documents require a different reviewed scope contract.
    if re.search(r"\b(?:PTA|PESETAS|USD|GBP|JPY|DOLARES)\b|[$£¥]", text.upper()):
        return None
    net_lines = [line for line in compact if "LIQUIDOTOTALAPERCIBIR" in line]
    if len(net_lines) != 1 or (match := _NET.search(net_lines[0])) is None:
        return None
    printed = ExactDecimal(int(match[1].replace(".", "").replace(",", "")), 2)
    if printed != value.value:
        return None
    return CurrencyEvidence(
        document_id,
        version_id,
        extraction_id,
        observation_id,
        fact_id,
        file_sha256,
        page,
        sha256(text.encode()).hexdigest(),
        printed,
        CurrencyCode("EUR"),
    )


def source_roots() -> dict[str, Path]:
    """Reuse the existing local ingestion manifest, without modifying configuration."""
    from src.canonical_build import BuildError, load_config
    from src.cli_config import REPOSITORY_ROOT

    try:
        build = load_config(REPOSITORY_ROOT / "data/private/canonical-build.json")
    except (OSError, ValueError, BuildError):
        return {}
    return {str(c.corpus.corpus_id): c.source for c in build.corpora}


def attach_currency(
    inspector: CanonicalInspector,
    rows: Sequence[dict[str, Any]],
    sources: Mapping[str, DocumentConcepts],
    roots: Mapping[str, Path],
) -> None:
    """Attach ephemeral proof to a timeline copy; never change value.currency.

    Only reviewed single-page/single-version sources are supported in this first
    evidence contract. Other formats and alternative versions remain unchanged.
    """
    for row in rows:
        if (
            row["series"] != "Neto"
            or row["value"]["status"] != "certified"
            or row["value"].get("currency") is not None
            or not row.get("observation_id")
        ):
            continue
        source = sources.get(row["document_id"])
        if source is None or len(source.version_ids) != 1:
            continue
        extractions = [
            e
            for e in source.extractions
            if (e.extractor_name, e.extractor_revision) == ("InsisParser", INSIS_REVISION)
        ]
        if len(extractions) != 1:
            continue
        extraction = extractions[0]
        if tuple(row["source_version_ids"]) != (extraction.version_id,):
            continue
        detail = inspector.explain(row["observation_id"], CertificationRequirements())
        targets = [
            f
            for f in detail["supporting_facts"]
            if f["fact"].fact_key == "nomina.liquido_percibir"
            and f["fact"].extraction_id == extraction.extraction_id
        ]
        if (
            detail["certification"]["status"] != "certified"
            or len(targets) != 1
            or targets[0]["fact"].value != detail["observation"].value
        ):
            continue
        fact = targets[0]["fact"]
        pages = inspector.fact_pages(fact.fact_id)
        if (
            not pages
            or {p.page_number for p in pages} != {1}
            or {p.version_id for p in pages} != {extraction.version_id}
        ):
            continue
        version = inspector.document(row["document_id"])["versions"][0]
        if {p.page_number for p in version["pages"]} != {1}:
            continue
        for location in version["locations"]:
            root = roots.get(location["corpus_id"])
            if root is None:
                continue
            path = (root / location["relative_path"]).resolve()
            if not path.is_relative_to(root.resolve()):
                continue
            try:
                data = path.read_bytes()
                if sha256(data).hexdigest() != version["source_file"].sha256:
                    continue
                with pdfplumber.open(BytesIO(data)) as pdf:
                    if len(pdf.pages) != 1:
                        continue
                    text = pdf.pages[0].extract_text() or ""
            except (OSError, ValueError, PdfminerException):
                continue
            evidence = attest_net(
                document_id=row["document_id"],
                version_id=extraction.version_id,
                extraction_id=extraction.extraction_id,
                observation_id=row["observation_id"],
                fact_id=fact.fact_id,
                file_sha256=version["source_file"].sha256,
                parser=extraction.extractor_name,
                revision=extraction.extractor_revision,
                page=1,
                value=fact.value,
                text=text,
            )
            if evidence is not None:
                row["currency_evidence"] = evidence
            break
