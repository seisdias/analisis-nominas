"""Ingest Exceltic PDFs, distinguishing physical files from economic payrolls."""

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.services.database_service import DatabaseService
from src.services.ingestion_service import NoExtractableTextError, parse_nomina_pdf


@dataclass
class IngestionResult:
    found: int = 0
    processed: int = 0
    omitted: int = 0
    failed: int = 0
    economic_documents: int = 0
    final_rows: int = 0


def run_ingestion(
    pdf_dir: str | Path = "data/test/exceltic",
    db_path: str = "data/runtime/nominas.sqlite",
) -> IngestionResult:
    directory = Path(pdf_dir)
    if not directory.is_dir():
        raise ValueError(f"No existe el directorio de entrada: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not files:
        raise ValueError(f"No hay PDFs en: {directory}")
    database = DatabaseService(db_path=db_path)
    result = IngestionResult(found=len(files))
    written_ids: set[str] = set()
    try:
        database.init_db()
        for path in files:
            try:
                doc = parse_nomina_pdf(path, filename=path.name)
                if doc.cif != "B84242767":
                    raise ValueError("El documento no pertenece a EXCELTIC")
                # Every physical file reaches the existing UPSERT. Identity comes
                # from the parser's printed period/company, never a filename/hash.
                database.guardar_documento(doc)
            except NoExtractableTextError:
                result.omitted += 1
                print(f"OMITIDO / PENDIENTE: {path.name} — sin texto extraíble; sin OCR ni persistencia")
            except Exception as exc:
                result.failed += 1
                print(f"ERROR: {path.name} — {type(exc).__name__}: {exc}")
            else:
                result.processed += 1
                written_ids.add(doc.id)
                print(f"OK: {path.name}")
        result.economic_documents = len(written_ids)
        result.final_rows = sum(
            row["cif"] == "B84242767" for row in database.obtener_todos()
        )
    finally:
        # File-backed operations already close their own connections. The service
        # retains one connection only for :memory:; this run owns that lifecycle.
        if database._shared_conn is not None:
            database._shared_conn.close()
    print(
        f"EXCELTIC: encontrados={result.found}, procesados={result.processed}, "
        f"omitidos={result.omitted}, fallos={result.failed}, "
        f"documentos_economicos={result.economic_documents}, filas_finales={result.final_rows}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", default="data/test/exceltic", help="Directorio de PDFs")
    parser.add_argument("--db", default="data/runtime/nominas.sqlite", help="Ruta SQLite de destino")
    args = parser.parse_args(argv)
    try:
        result = run_ingestion(pdf_dir=args.pdf_dir, db_path=args.db)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}")
        return 1
    return int(result.failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
