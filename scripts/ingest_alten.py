"""Store ALTEN documentary evidence only. No economic selection or publication."""

import argparse
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from src.extraction import ExtractedDocument
from src.parsers.alten_parser import AltenParser
from src.services.database_service import DatabaseService
from src.services.ingestion_service import extract_pdf_document


def is_certificate(document: ExtractedDocument) -> bool:
    """Recognize the observed two-page annual form, not arbitrary parser failures.

    These forms have image backgrounds: their titles are NOT extractable text.
    The textual evidence is repeated annual fields, issuer identity and three
    fiscal amounts (two on a row, one below) on page one, and three repeated
    annual fields with no amounts on page two. Check both layout and text.
    No OCR, filename, fiscal amount or particular year determines this decision.
    Unknown forms remain errors, never silently excluded as certificates.
    """
    pages = document.pages
    if pages is None or len(pages) != 2:
        return False
    annual_fields = []
    for p, count in zip(pages, (2, 3), strict=True):
        text = ' '.join(p.text.split())
        if not re.search(r'\bB05366117\b', text):
            return False
        try:
            AltenParser.template(p.text)
        except ValueError:
            return False
        if re.search(r'Periodo\s*de\s*liquidaci[oó]n|DEVENGOS|LIQUIDO', text, re.IGNORECASE):
            return False
        years = re.findall(r'(?m)^\s*(\d{4})\s*$', p.text)
        if len(years) != count or p.words is None:
            return False
        annual_fields.extend(years)
    if len(set(annual_fields)) != 1:
        return False
    money = r'-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}'
    amounts = [w for w in pages[0].words or () if re.fullmatch(money, w.text)]
    if len(amounts) != 3 or re.search(money, pages[1].text):
        return False
    if len(re.findall(money, pages[0].text)) != 3:
        return False
    amounts.sort(key=lambda w: (w.top, w.x0))
    a, b, c = amounts
    years = sorted((w for w in pages[0].words or () if w.text == annual_fields[0]), key=lambda w: w.top)
    if len(years) != 2:
        return False
    tolerance = max(a.bottom - a.top, b.bottom - b.top) / 2
    return (
        abs(a.top - b.top) <= tolerance and a.x1 < b.x0
        and years[0].bottom < min(a.top, b.top)
        and max(a.bottom, b.bottom) < c.top and c.bottom < years[1].top
    )


@dataclass
class IngestionResult:
    found: int = 0
    payroll_pdfs: int = 0
    certificates: int = 0
    versions: int = 0
    periods: int = 0
    stored_versions: int = 0
    new_versions: int = 0
    idempotent_versions: int = 0
    failed: int = 0


def run_ingestion(
    pdf_dir: str | Path = 'data/test/alten', db_path: str = 'data/runtime/nominas.sqlite',
) -> IngestionResult:
    directory = Path(pdf_dir)
    if not directory.is_dir():
        raise ValueError(f'No existe el directorio de entrada: {directory}')
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == '.pdf')
    if not files:
        raise ValueError(f'No hay PDFs en: {directory}')
    db = DatabaseService(db_path)
    result = IngestionResult(found=len(files))
    try:
        db.init_db()
        parser = AltenParser()
        for path in files:
            try:
                # Hash and extraction use exactly the same bytes, even if the file changes later.
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                document = extract_pdf_document(BytesIO(content))
                if is_certificate(document):
                    result.certificates += 1
                    print(f'EXCLUIDO: {path.name} — certificado anual; sin persistencia')
                    continue
                docs = parser.parse_pages(document)
                new, identical = db.guardar_pdf_documental(
                    digest, path.name, list(enumerate(docs, start=1)),
                )
            except Exception as exc:
                result.failed += 1
                print(f'ERROR: {path.name} — {type(exc).__name__}: {exc}')
            else:
                result.payroll_pdfs += 1
                result.versions += len(docs)
                result.new_versions += new
                result.idempotent_versions += identical
                print(f'OK DOCUMENTAL: {path.name} — versiones={len(docs)}')
        keys = {p['period_key'] for p in db.obtener_periodos_documentales() if p['cif'] == 'B05366117'}
        result.periods = len(keys)
        result.stored_versions = sum(v['period_key'] in keys for v in db.obtener_versiones_documentales())
    finally:
        if db._shared_conn is not None:
            db._shared_conn.close()
    print(
        f'ALTEN documental: encontrados={result.found}, pdfs_nomina={result.payroll_pdfs}, '
        f'certificados_excluidos={result.certificates}, versiones_procesadas={result.versions}, '
        f'periodos={result.periods}, versiones_persistidas={result.stored_versions}, '
        f'nuevas={result.new_versions}, idempotentes={result.idempotent_versions}, fallos={result.failed}'
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-dir', default='data/test/alten', help='Directorio de PDFs')
    parser.add_argument('--db', default='data/runtime/nominas.sqlite', help='SQLite documental de destino')
    args = parser.parse_args(argv)
    try:
        result = run_ingestion(pdf_dir=args.pdf_dir, db_path=args.db)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'ERROR: {exc}')
        return 1
    return int(result.failed > 0)


if __name__ == '__main__':
    raise SystemExit(main())
