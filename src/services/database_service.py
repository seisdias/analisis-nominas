import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from src.models.documento_laboral import DocumentoLaboral, TipoDocumento
from src.models.nomina import Nomina


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
            self._shared_conn.execute("PRAGMA foreign_keys = ON")

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self):
        conn = self._get_connection()
        try:
            with conn:
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
                self._init_documentary_tables(conn)
        finally:
            if conn is not self._shared_conn:
                conn.close()

    def reset_db(self):
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS documentos")
        finally:
            if conn is not self._shared_conn:
                conn.close()
        self.init_db()

    def guardar_documento(self, doc: DocumentoLaboral):
        if isinstance(doc, Nomina) and "".join(doc.cif.split()).upper() == "B05366117":
            raise ValueError("ALTEN requires documental persistence and explicit economic resolution")
        conn = self._get_connection()
        try:
            with conn:
                cursor = conn.cursor()

                salario_base = getattr(doc, 'salario_base', 0.0)
                total_devengado = getattr(doc, 'total_devengado', 0.0)
                total_deducir = getattr(doc, 'total_deducir', 0.0)
                liquido_percibir = getattr(doc, 'liquido_percibir', 0.0)
                retribuciones_integras = getattr(doc, 'retribuciones_integras', 0.0)
                retenciones_practicadas = getattr(doc, 'retenciones_practicadas', 0.0)

                cursor.execute(
                    """
                    INSERT INTO documentos (
                        id, anio, mes, periodo, empresa, cif, tipo,
                        salario_base, total_devengado, total_deducir, liquido_percibir,
                        retribuciones_integras, retenciones_practicadas,
                        observaciones, es_procesable, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        anio = excluded.anio,
                        mes = excluded.mes,
                        periodo = excluded.periodo,
                        empresa = excluded.empresa,
                        cif = excluded.cif,
                        tipo = excluded.tipo,
                        salario_base = excluded.salario_base,
                        total_devengado = excluded.total_devengado,
                        total_deducir = excluded.total_deducir,
                        liquido_percibir = excluded.liquido_percibir,
                        retribuciones_integras = excluded.retribuciones_integras,
                        retenciones_practicadas = excluded.retenciones_practicadas,
                        observaciones = excluded.observaciones,
                        es_procesable = excluded.es_procesable,
                        payload = excluded.payload
                    """,
                    (
                        doc.id,
                        doc.anio,
                        doc.mes,
                        doc.periodo,
                        doc.empresa,
                        doc.cif,
                        doc.tipo.value,
                        salario_base,
                        total_devengado,
                        total_deducir,
                        liquido_percibir,
                        retribuciones_integras,
                        retenciones_practicadas,
                        doc.observaciones,
                        int(doc.es_procesable),
                        json.dumps(asdict(doc), ensure_ascii=False),
                    ),
                )
        finally:
            if conn is not self._shared_conn:
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
            with conn:
                conn.execute("DELETE FROM documentos WHERE id = ?", (document_id,))
        finally:
            if conn is not self._shared_conn:
                conn.close()

    @staticmethod
    def _init_documentary_tables(conn: sqlite3.Connection) -> None:
        # Additive evidence storage. No rows from these tables enter economic readers.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payroll_periods (
                period_key TEXT PRIMARY KEY NOT NULL,
                cif TEXT NOT NULL,
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT NOT NULL,
                tipo TEXT NOT NULL,
                resolution_status TEXT NOT NULL DEFAULT 'UNRESOLVED'
                    CHECK(resolution_status IN ('UNRESOLVED', 'RESOLVED')),
                resolution_kind TEXT CHECK(resolution_kind IN ('SELECTED_VERSION', 'RECONCILED')),
                selected_version_key TEXT,
                economic_payload TEXT,
                resolution_note TEXT,
                resolution_evidence TEXT,
                resolved_at TEXT,
                UNIQUE(cif, fecha_inicio, fecha_fin, tipo),
                FOREIGN KEY(period_key, selected_version_key)
                    REFERENCES payroll_document_versions(period_key, version_key),
                CHECK(
                    (resolution_status = 'UNRESOLVED'
                        AND resolution_kind IS NULL AND selected_version_key IS NULL
                        AND economic_payload IS NULL AND resolution_note IS NULL
                        AND resolution_evidence IS NULL AND resolved_at IS NULL)
                    OR
                    (resolution_status = 'RESOLVED' AND resolution_kind IS NOT NULL
                        AND resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0
                        AND resolution_evidence IS NOT NULL AND length(trim(resolution_evidence)) > 0
                        AND resolved_at IS NOT NULL AND length(trim(resolved_at)) > 0
                        AND (
                            (resolution_kind = 'SELECTED_VERSION'
                                AND selected_version_key IS NOT NULL AND economic_payload IS NULL)
                            OR (resolution_kind = 'RECONCILED'
                                AND selected_version_key IS NULL AND economic_payload IS NOT NULL
                                AND CASE WHEN json_valid(economic_payload)
                                    THEN json_type(economic_payload) = 'object' ELSE 0 END)
                        ))
                )
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payroll_document_versions (
                version_key TEXT PRIMARY KEY NOT NULL,
                period_key TEXT NOT NULL REFERENCES payroll_periods(period_key),
                pdf_sha256 TEXT NOT NULL,
                page_number INTEGER NOT NULL CHECK(typeof(page_number) = 'integer' AND page_number >= 1),
                source_filename TEXT NOT NULL,
                payload TEXT NOT NULL CHECK(CASE WHEN json_valid(payload)
                    THEN json_type(payload) = 'object' ELSE 0 END),
                UNIQUE(pdf_sha256, page_number),
                UNIQUE(period_key, version_key)
            )
        """)

    @contextmanager
    def _documentary_transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._get_connection()
        try:
            if conn.in_transaction:
                raise ValueError("Cannot nest a documentary transaction")
            with conn:
                # Serialize compare-then-insert, including concurrent reingestions.
                conn.execute("BEGIN IMMEDIATE")
                yield conn
        finally:
            if conn is not self._shared_conn:
                conn.close()

    @staticmethod
    def _period_identity(doc: Nomina) -> tuple[str, str, str, str, str]:
        if not isinstance(doc, Nomina) or not doc.cif or '|' in doc.cif:
            raise ValueError("Invalid documentary payroll identity")
        if doc.tipo != TipoDocumento.NOMINA_ORDINARIA:
            raise ValueError("Documentary storage requires an ordinary payroll")
        if doc.fecha_inicio is None or doc.fecha_fin is None:
            raise ValueError("Missing documentary payroll dates")
        start, end = date.fromisoformat(doc.fecha_inicio), date.fromisoformat(doc.fecha_fin)
        if start > end or start.isoformat() != doc.fecha_inicio or end.isoformat() != doc.fecha_fin:
            raise ValueError("Invalid documentary payroll dates")
        fields = (doc.cif, doc.fecha_inicio, doc.fecha_fin, doc.tipo.value)
        return ('|'.join(fields), *fields)

    @staticmethod
    def _ensure_period(conn: sqlite3.Connection, identity: tuple[str, str, str, str, str]) -> str:
        key = identity[0]
        row = conn.execute(
            'SELECT period_key,cif,fecha_inicio,fecha_fin,tipo FROM payroll_periods WHERE period_key=?',
            (key,),
        ).fetchone()
        if row is None:
            conn.execute('''INSERT INTO payroll_periods
                (period_key,cif,fecha_inicio,fecha_fin,tipo) VALUES (?,?,?,?,?)''', identity)
        elif tuple(row) != identity:
            raise ValueError("Conflicting documentary period identity")
        # Existing resolution is deliberately neither read as priority nor updated.
        return key

    def garantizar_periodo_documental(self, doc: Nomina) -> str:
        identity = self._period_identity(doc)
        with self._documentary_transaction() as conn:
            return self._ensure_period(conn, identity)

    def guardar_pdf_documental(
        self, pdf_sha256: str, source_filename: str, pages: list[tuple[int, Nomina]],
    ) -> tuple[int, int]:
        """Atomically insert a PDF's evidence; return (new versions, identical versions).

        Conflicting evidence is an error, never an update. The first source filename
        is retained on renames; it is provenance only, not documentary identity.
        """
        if not re.fullmatch(r'[0-9a-f]{64}', pdf_sha256):
            raise ValueError("Invalid PDF SHA256")
        if not source_filename or Path(source_filename).name != source_filename:
            raise ValueError("Source filename must be a basename")
        if not pages or any(type(n) is not int or n < 1 for n, _ in pages):
            raise ValueError("Invalid documentary page number")
        if len({n for n, _ in pages}) != len(pages):
            raise ValueError("Duplicate documentary page number")
        new = identical = 0
        with self._documentary_transaction() as conn:
            for number, doc in pages:
                identity = self._period_identity(doc)
                payload = json.dumps(doc.to_dict(), ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False)
                key = f'sha256:{pdf_sha256}:page:{number}'
                existing = conn.execute('''SELECT period_key,pdf_sha256,page_number,payload
                    FROM payroll_document_versions WHERE version_key=?''', (key,)).fetchone()
                period_key = self._ensure_period(conn, identity)
                values = (period_key, pdf_sha256, number, payload)
                if existing is not None:
                    if tuple(existing) != values:
                        raise ValueError("Documentary version payload/identity conflict")
                    identical += 1
                    continue
                conn.execute('''INSERT INTO payroll_document_versions
                    (version_key,period_key,pdf_sha256,page_number,source_filename,payload)
                    VALUES (?,?,?,?,?,?)''', (key, period_key, pdf_sha256, number, source_filename, payload))
                new += 1
        return new, identical

    def guardar_version_documental(
        self, doc: Nomina, pdf_sha256: str, page_number: int, source_filename: str,
    ) -> bool:
        """Single-page convenience; multipage callers must use guardar_pdf_documental."""
        new, _ = self.guardar_pdf_documental(pdf_sha256, source_filename, [(page_number, doc)])
        return bool(new)

    def _documentary_rows(self, sql: str, params: tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            if conn is not self._shared_conn:
                conn.close()

    def obtener_periodos_documentales(self) -> List[Dict[str, Any]]:
        return self._documentary_rows('SELECT * FROM payroll_periods ORDER BY period_key')

    def obtener_versiones_documentales(self) -> List[Dict[str, Any]]:
        return self._documentary_rows('SELECT * FROM payroll_document_versions ORDER BY version_key')

    def obtener_versiones_de_periodo(self, period_key: str) -> List[Dict[str, Any]]:
        return self._documentary_rows(
            'SELECT * FROM payroll_document_versions WHERE period_key=? ORDER BY version_key',
            (period_key,),
        )
