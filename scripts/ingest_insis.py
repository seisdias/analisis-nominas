"""Ingest local INSIS4 payrolls; use --db to select an isolated SQLite database."""

import argparse
from dataclasses import dataclass
from pathlib import Path

from src.services.database_service import DatabaseService
from src.services.ingestion_service import NoExtractableTextError, parse_nomina_pdf


@dataclass
class IngestionResult:
    processed: int = 0
    omitted: int = 0
    failed: int = 0


def run_ingestion(
    pdf_dir: str | Path = "data/test/insis4",
    db_path: str = "data/runtime/nominas.sqlite",
) -> IngestionResult:
    directory = Path(pdf_dir)
    if not directory.is_dir():
        raise ValueError(f"No existe el directorio de entrada: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not files:
        raise ValueError(f"No hay PDFs en: {directory}")
    database = DatabaseService(db_path=db_path)
    database.init_db()
    result = IngestionResult()
    for path in files:
        try:
            doc = parse_nomina_pdf(path, filename=path.name)
            if doc.cif != "B84225283":
                raise ValueError("El documento no pertenece a INSIS4")
            database.guardar_documento(doc)
        except NoExtractableTextError:
            result.omitted += 1
            print(f"OMITIDO / PENDIENTE: {path.name} — sin texto extraíble; sin OCR ni persistencia")
        except Exception as exc:
            result.failed += 1
            print(f"ERROR: {path.name} — {type(exc).__name__}: {exc}")
        else:
            result.processed += 1
            print(f"OK: {path.name}")
    print(f"INSIS4: procesados={result.processed}, omitidos={result.omitted}, fallos={result.failed}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/runtime/nominas.sqlite", help="Ruta SQLite de destino")
    parser.add_argument("--pdf-dir", default="data/test/insis4",
                        help="Directorio de PDFs (legacy: data/testdata/insis4)")
    args = parser.parse_args(argv)
    try:
        result = run_ingestion(pdf_dir=args.pdf_dir, db_path=args.db)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return int(result.failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
