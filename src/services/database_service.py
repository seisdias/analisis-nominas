import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models.documento_laboral import DocumentoLaboral, TipoDocumento


class DatabaseService:
    def __init__(self, db_path: str = "data/runtime/nominas.sqlite"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared_conn: Optional[sqlite3.Connection] = None

        # Si es en memoria, se mantiene una sola conexión viva durante el ciclo del servicio
        if self.db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:")
            self._shared_conn.row_factory = sqlite3.Row

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documentos (
                id TEXT PRIMARY KEY,
                anio INTEGER NOT NULL,
                mes INTEGER NOT NULL,
                periodo TEXT NOT NULL,
                empresa TEXT NOT NULL,
                cif TEXT NOT NULL,
                tipo TEXT NOT NULL,
                salario_base REAL DEFAULT 0.0,
                total_devengado REAL DEFAULT 0.0,
                total_deducir REAL DEFAULT 0.0,
                liquido_percibir REAL DEFAULT 0.0,
                retribuciones_integras REAL DEFAULT 0.0,
                retenciones_practicadas REAL DEFAULT 0.0,
                observaciones TEXT DEFAULT '',
                es_procesable INTEGER DEFAULT 1,
                payload TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.commit()
        if not self._shared_conn:
            conn.close()

    def reset_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS documentos")
        conn.commit()
        if not self._shared_conn:
            conn.close()
        self.init_db()

    def guardar_documento(self, doc: DocumentoLaboral):
        conn = self._get_connection()
        cursor = conn.cursor()

        salario_base = getattr(doc, 'salario_base', 0.0)
        total_devengado = getattr(doc, 'total_devengado', 0.0)
        total_deducir = getattr(doc, 'total_deducir', 0.0)
        liquido_percibir = getattr(doc, 'liquido_percibir', 0.0)
        retribuciones_integras = getattr(doc, 'retribuciones_integras', 0.0)
        retenciones_practicadas = getattr(doc, 'retenciones_practicadas', 0.0)

        cursor.execute("""
            INSERT INTO documentos (
                id, anio, mes, periodo, empresa, cif, tipo,
                salario_base, total_devengado, total_deducir, liquido_percibir,
                retribuciones_integras, retenciones_practicadas, observaciones, es_procesable, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            doc.id, doc.anio, doc.mes, doc.periodo, doc.empresa, doc.cif, doc.tipo.value,
            salario_base, total_devengado, total_deducir, liquido_percibir,
            retribuciones_integras, retenciones_practicadas, doc.observaciones, int(doc.es_procesable), json.dumps(asdict(doc), ensure_ascii=False)
        ))
        conn.commit()
        if not self._shared_conn:
            conn.close()

    def obtener_todos(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documentos")
        rows = [{**json.loads(row["payload"]), **dict(row)} for row in cursor.fetchall()]
        if not self._shared_conn:
            conn.close()
        return rows

    def obtener_documentos_por_empresa(self, empresa: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documentos WHERE empresa = ?", (empresa,))
        rows = [{**json.loads(row["payload"]), **dict(row)} for row in cursor.fetchall()]
        if not self._shared_conn:
            conn.close()
        return rows

    def obtener_certificados(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM documentos WHERE tipo = ?", (TipoDocumento.CERTIFICADO_RETENCIONES.value,))
        rows = [{**json.loads(row["payload"]), **dict(row)} for row in cursor.fetchall()]
        if not self._shared_conn:
            conn.close()
        return rows
    def eliminar_documento(self, document_id: str) -> None:
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM documentos WHERE id = ?", (document_id,))
            conn.commit()
        finally:
            if not self._shared_conn:
                conn.close()
