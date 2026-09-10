# -*- coding: utf-8 -*-
import glob
import os

from src.services.database_service import DatabaseService
from src.services.ingestion_service import parse_nomina_pdf


def run_ingestion():
    pdf_dir = "data/test/coritel"
    db_path = "data/runtime/nominas.sqlite"

    pdf_files = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))

    if not pdf_files:
        print(f"❌ No se encontraron archivos PDF en '{pdf_dir}'.")
        return

    print(f"🚀 Iniciando procesamiento de {len(pdf_files)} PDFs...\n")

    db_service = DatabaseService(db_path=db_path)

    db_service.init_db()

    exitos = 0
    descuadres = 0

    for pdf_path in pdf_files:
        filename = os.path.basename(pdf_path)
        try:
            nomina = parse_nomina_pdf(pdf_path, filename=filename)

            # Validación de cuadre matemático (Tolerancia: 0.02€)
            calculado = round(nomina.total_devengado - nomina.total_deducir, 2)
            diferencia = abs(calculado - nomina.liquido_percibir)

            if diferencia > 0.02:
                print(
                    f"⚠️  [DESCUADRE] {filename}: Leído={nomina.liquido_percibir}€ | Calc={calculado}€ (Diff: {diferencia:.2f}€)")
                descuadres += 1
                continue
            else:
                print(f"✅ [OK] {filename} -> Periodo: {nomina.periodo} | Líquido: {nomina.liquido_percibir}€")

            # Persistencia en BD
            db_service.guardar_documento(nomina)
            exitos += 1

        except Exception as e:
            print(f"❌ [ERROR] {filename}: {e}")

    print("\n" + "=" * 50)
    print(f"📊 Resumen: {exitos}/{len(pdf_files)} procesados correctamente. Descuadres detectados: {descuadres}.")
    print("=" * 50)


if __name__ == "__main__":
    run_ingestion()
