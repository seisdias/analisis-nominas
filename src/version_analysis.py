"""Read-only selection of documentary occurrences from an existing A.3 decision."""

import json
from dataclasses import dataclass
from enum import StrEnum

from src.alten_projection import FIELDS, NAME, REVISION, SOURCE_REVISION
from src.alten_resolutions import decode_resolutions
from src.canonical.documents import extraction_id
from src.canonical.economics import fact_fingerprint
from src.canonical.serialization import canonical_sha256
from src.canonical.values import ValueState
from src.document_concepts import DocumentConcepts, ExtractionConcepts, project_extraction

# Reviewed implementation embedded in A.3 v2 manifests. A new producer requires review.
_A3_IMPLEMENTATION = "c0995bb5e4e9d6088a7cdbffba13da6bf3fbc5f89ccd5c49618c5ad3ccfa2537"


class Selection(StrEnum):
    SINGLE = "Versión única"
    AUTHORIZED = "Versión autorizada por resolución A.3"
    EXCLUDED = "Sin versión analítica autorizada"


@dataclass(frozen=True)
class VersionAnalysis:
    status: Selection
    extraction: ExtractionConcepts | None
    reason: str
    projection_id: str | None = None
    review: str | None = None


def excluded(reason: str) -> VersionAnalysis:
    return VersionAnalysis(Selection.EXCLUDED, None, reason)


def _verified(e: ExtractionConcepts) -> bool:
    facts = {f.fact.fact_key: f.fact.value for f in e.facts}
    return (
        len(facts) == len(e.facts)
        and canonical_sha256(facts) == e.content_hash
        and all(f.fact.extraction_id == e.extraction_id for f in e.facts)
    )


def analytical_version(s: DocumentConcepts) -> VersionAnalysis:
    """Inspection widget state is deliberately absent from the selection inputs."""
    versions = set(s.version_ids)
    if (
        not versions
        or len(versions) != len(s.version_ids)
        or any(
            e.document_id != s.document_id or e.version_id not in versions for e in s.extractions
        )
    ):
        return excluded("Inventario documental incompatible")
    if len(versions) == 1:
        rows = [e for e in s.extractions if e.concepts]
        if len(rows) != 1:
            return excluded(
                "Desglose no disponible"
                if not rows
                else "Varias extracciones con conceptos: sin selección autorizada"
            )
        return VersionAnalysis(Selection.SINGLE, rows[0], "Una extracción con desglose")
    projections = [e for e in s.extractions if e.extractor_name == NAME]
    if not projections:
        return excluded("Multiversión sin resolución documental A.3")
    if len(projections) != 1 or projections[0].extractor_revision != REVISION:
        return excluded("Proyección A.3 ambigua o de revisión incompatible")
    projection = projections[0]
    if not _verified(projection):
        return excluded("Huella de la proyección A.3 incompatible")
    pf = {f.fact.fact_key: f.fact.value for f in projection.facts}
    evidence = pf.get("projection/manifest")
    if (
        evidence is None
        or evidence.state != ValueState.PRESENT
        or not isinstance(evidence.value, str)
    ):
        return excluded("Falta el manifiesto de procedencia A.3")
    try:
        manifest = json.loads(evidence.value)
        if (
            not isinstance(manifest, dict)
            or manifest.get("contract") != REVISION
            or manifest.get("implementation") != _A3_IMPLEMENTATION
        ):
            raise ValueError
        if (
            extraction_id(projection.version_id, NAME, REVISION, canonical_sha256(manifest))
            != projection.extraction_id
        ):
            raise ValueError
        (choice,) = decode_resolutions(json.dumps(manifest["resolution"]).encode())
    except (ValueError, TypeError, KeyError):
        return excluded("Manifiesto o resolución A.3 inválidos")
    if (
        choice.document_id != s.document_id
        or choice.version_id != projection.version_id
        or set(choice.expected_version_ids) != versions
    ):
        return excluded("La resolución no corresponde al documento y a su inventario vigente")
    originals = [e for e in s.extractions if e != projection]
    if (
        len(originals) != len(versions)
        or {e.version_id for e in originals} != versions
        or any(
            (e.extractor_name, e.extractor_revision) != ("alten-legacy-evidence", SOURCE_REVISION)
            for e in originals
        )
    ):
        return excluded("Extracciones originales ausentes, alternativas o incompatibles")
    original = next(e for e in originals if e.version_id == choice.version_id)
    if (
        original.extraction_id != manifest.get("source_extraction")
        or original.content_hash != manifest.get("source_content_hash")
        or not _verified(original)
    ):
        return excluded("El manifiesto no acredita la extracción original")
    provenance = {
        f.fact.fact_key: {
            "fact_id": str(f.fact.fact_id),
            "fingerprint": fact_fingerprint(f.fact),
            "pages": list(f.pages),
        }
        for f in original.facts
    }
    for key in ("source_extraction", "source_content_hash", "ingest_run"):
        field = pf.get("projection/" + key)
        if field is None or field.state != ValueState.PRESENT or field.value != manifest.get(key):
            return excluded("Metadatos de procedencia contradictorios")
    if provenance != manifest.get("sources") or any(
        not f.pages for f in original.facts if f.fact.fact_key.startswith("payload/")
    ):
        return excluded("Hechos o páginas incompatibles con la resolución")
    try:
        rebuilt = project_extraction(
            s.document_id,
            original.version_id,
            original.extraction_id,
            [f.fact for f in original.facts],
            pages={f.fact.fact_id: f.pages for f in original.facts},
        )
    except ValueError:
        return excluded("Procedencia de conceptos incompatible")
    if rebuilt.concepts != original.concepts:
        return excluded("Ocurrencias incompatibles con los hechos originales")
    expected = {
        "nomina." + f.fact.fact_key.removeprefix("payload/"): f.fact.value
        for f in original.facts
        if f.fact.fact_key in {"payload/" + field for field in FIELDS}
    }
    if expected != {k: v for k, v in pf.items() if k.startswith("nomina.")}:
        return excluded("Totales o contexto incompatibles con la extracción autorizada")
    return VersionAnalysis(
        Selection.AUTHORIZED,
        original,
        "Manifiesto A.3 e inventario verificados",
        projection.extraction_id,
        choice.reason,
    )
