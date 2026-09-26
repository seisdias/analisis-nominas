"""Synthetic evidence storage; never uses private databases or salary data."""
import json
import sqlite3
from dataclasses import replace

import pytest

from src.models.nomina import Nomina
from src.parsers.alten_parser import AltenParser
from src.services.database_service import DatabaseService
from tests.test_alten_parser import page

SHA = 'a' * 64
OTHER_SHA = 'b' * 64


@pytest.fixture(params=['memory', 'file'])
def db(request, tmp_path):
    service = DatabaseService(':memory:' if request.param == 'memory' else str(tmp_path / 'test.sqlite'))
    service.init_db()
    try:
        yield service
    finally:
        if service._shared_conn is not None:
            service._shared_conn.close()


@pytest.fixture
def doc():
    return AltenParser().parse_extracted(page())


def execute(db, sql, params=()):
    conn = db._get_connection()
    try:
        with conn:
            return conn.execute(sql, params).fetchall()
    finally:
        if conn is not db._shared_conn:
            conn.close()


def test_schema_repeat_foreign_keys(db):
    db.init_db()
    assert execute(db, 'PRAGMA foreign_keys')[0][0] == 1
    names = {r[0] for r in execute(db, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'documentos', 'payroll_periods', 'payroll_document_versions'} <= names


def test_roundtrip_identity_and_rename(db, doc):
    assert db.guardar_version_documental(doc, SHA, 1, 'first.pdf') is True
    first = db.obtener_versiones_documentales()
    assert db.guardar_version_documental(doc, SHA, 1, 'renamed.pdf') is False
    assert db.obtener_versiones_documentales() == first
    row = first[0]
    assert row['version_key'] == f'sha256:{SHA}:page:1'
    assert row['period_key'] == AltenParser.period_key(doc)
    restored = Nomina.from_dict(json.loads(row['payload']))
    assert restored == doc
    assert restored.prorrata_pagas_extra is None
    assert restored.conceptos == doc.conceptos
    assert db.obtener_versiones_de_periodo(row['period_key']) == first
    assert db.obtener_todos() == []
    assert db.obtener_documentos_por_empresa(doc.empresa) == []
    period = db.obtener_periodos_documentales()[0]
    assert period['resolution_status'] == 'UNRESOLVED'
    assert all(period[k] is None for k in (
        'resolution_kind', 'selected_version_key', 'economic_payload',
        'resolution_note', 'resolution_evidence', 'resolved_at',
    ))


def test_none_zero_and_conflicting_payload(db, doc):
    db.guardar_version_documental(doc, SHA, 1, 'file.pdf')
    with pytest.raises(ValueError, match='conflict'):
        db.guardar_version_documental(replace(doc, pror_otros=0.0), SHA, 1, 'file.pdf')
    assert Nomina.from_dict(json.loads(db.obtener_versiones_documentales()[0]['payload'])) == doc
    zero = replace(doc, prorrata_pagas_extra=0.0)
    db.guardar_version_documental(zero, OTHER_SHA, 1, 'zero.pdf')
    assert {json.loads(r['payload'])['prorrata_pagas_extra'] for r in db.obtener_versiones_documentales()} == {None, 0.0}
    assert len(db.obtener_periodos_documentales()) == 1


@pytest.mark.parametrize('kind', ['SELECTED_VERSION', 'RECONCILED'])
def test_resolution_is_not_overwritten(db, doc, kind):
    db.guardar_version_documental(doc, SHA, 1, 'first.pdf')
    key = AltenParser.period_key(doc)
    execute(db, '''UPDATE payroll_periods SET resolution_status='RESOLVED',
        resolution_kind=?, selected_version_key=?, economic_payload=?,
        resolution_note='Synthetic explicit decision', resolution_evidence='Synthetic reference',
        resolved_at='2099-01-01T00:00:00Z' WHERE period_key=?''',
        (kind, f'sha256:{SHA}:page:1' if kind == 'SELECTED_VERSION' else None,
         '{}' if kind == 'RECONCILED' else None, key))
    before = db.obtener_periodos_documentales()
    db.guardar_version_documental(doc, SHA, 1, 'first.pdf')
    db.guardar_version_documental(replace(doc, categoria='Other'), OTHER_SHA, 1, 'second.pdf')
    assert db.obtener_periodos_documentales() == before
    assert len(db.obtener_versiones_documentales()) == 2
    assert db.obtener_todos() == []


@pytest.mark.parametrize('assignment', [
    "resolution_status='UNKNOWN'", "resolution_kind='SELECTED_VERSION'",
    "resolution_status='RESOLVED'", "economic_payload='{}'",
    "resolution_status='RESOLVED', resolution_kind='OTHER'",
    "resolution_status='RESOLVED', resolution_kind='RECONCILED', economic_payload='{}'",
    "resolution_status='RESOLVED', resolution_kind='RECONCILED', economic_payload='invalid', resolution_note='n', resolution_evidence='e', resolved_at='t'",
    "resolution_status='RESOLVED', resolution_kind='RECONCILED', economic_payload='{}', resolution_note='', resolution_evidence='e', resolved_at='t'",
])
def test_resolution_constraints(db, doc, assignment):
    db.garantizar_periodo_documental(doc)
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, 'UPDATE payroll_periods SET ' + assignment)
    assert db.obtener_periodos_documentales()[0]['resolution_status'] == 'UNRESOLVED'


def test_selected_version_must_belong_to_period(db, doc):
    db.guardar_version_documental(doc, SHA, 1, 'first.pdf')
    other = replace(doc, fecha_inicio='2098-03-01', fecha_fin='2098-03-31')
    db.guardar_version_documental(other, OTHER_SHA, 1, 'other.pdf')
    with pytest.raises(sqlite3.IntegrityError):
        execute(db, '''UPDATE payroll_periods SET resolution_status='RESOLVED',
            resolution_kind='SELECTED_VERSION', selected_version_key=?,
            resolution_note='n', resolution_evidence='e', resolved_at='t' WHERE period_key=?''',
            (f'sha256:{OTHER_SHA}:page:1', AltenParser.period_key(doc)))


def test_sql_constraints(db, doc):
    db.guardar_version_documental(doc, SHA, 1, 'first.pdf')
    for sql in (
        'UPDATE payroll_document_versions SET page_number=0',
        "UPDATE payroll_document_versions SET period_key='missing'",
        "UPDATE payroll_document_versions SET payload='invalid'",
        'DELETE FROM payroll_periods',
        '''INSERT INTO payroll_document_versions SELECT 'different-key', period_key,
           pdf_sha256, page_number, source_filename, payload FROM payroll_document_versions''',
        '''INSERT INTO payroll_periods (period_key,cif,fecha_inicio,fecha_fin,tipo)
           SELECT 'different-key',cif,fecha_inicio,fecha_fin,tipo FROM payroll_periods''',
    ):
        with pytest.raises(sqlite3.IntegrityError):
            execute(db, sql)


@pytest.mark.parametrize('sha,number', [('invalid', 1), (SHA, 0), (SHA, True), (SHA, 1.5)])
def test_bad_identity_rejected(db, doc, sha, number):
    with pytest.raises(ValueError):
        db.guardar_version_documental(doc, sha, number, 'file.pdf')
    assert db.obtener_periodos_documentales() == []


def test_inconsistent_period_identity_rejected(db, doc):
    key = db.garantizar_periodo_documental(doc)
    execute(db, "UPDATE payroll_periods SET cif='OTHER' WHERE period_key=?", (key,))
    with pytest.raises(ValueError, match='identity'):
        db.garantizar_periodo_documental(doc)


def test_atomic_real_sqlite_failure_and_existing_data(db, doc):
    db.guardar_version_documental(doc, OTHER_SHA, 1, 'previous.pdf')
    before = db.obtener_versiones_documentales()
    execute(db, '''CREATE TRIGGER fail_middle BEFORE INSERT ON payroll_document_versions
        WHEN NEW.page_number=2 BEGIN SELECT RAISE(ABORT, 'synthetic middle-page failure'); END''')
    with pytest.raises(sqlite3.IntegrityError):
        db.guardar_pdf_documental(SHA, 'package.pdf', [
            (1, replace(doc, fecha_inicio='2098-03-01', fecha_fin='2098-03-31')),
            (2, doc), (3, doc),
        ])
    assert db.obtener_versiones_documentales() == before
    assert len(db.obtener_periodos_documentales()) == 1
    if db._shared_conn is not None:
        assert not db._shared_conn.in_transaction
    execute(db, 'DROP TRIGGER fail_middle')
    assert db.guardar_pdf_documental(SHA, 'package.pdf', [(1, doc), (2, doc)]) == (2, 0)


def test_reset_preserves_evidence_and_economic_guard(db, doc):
    with pytest.raises(ValueError, match='ALTEN.*documental'):
        db.guardar_documento(doc)
    db.guardar_documento(replace(doc, cif='SYNTHETIC', empresa='Synthetic'))
    assert len(db.obtener_todos()) == 1
    db.guardar_version_documental(doc, SHA, 1, 'first.pdf')
    before = db.obtener_versiones_documentales()
    db.reset_db()
    assert db.obtener_todos() == []
    assert db.obtener_versiones_documentales() == before
    assert len(db.obtener_periodos_documentales()) == 1


def test_payload_conflict_rolls_back_earlier_pages_and_periods(db, doc):
    db.guardar_version_documental(doc, SHA, 2, 'package.pdf')
    before = db.obtener_versiones_documentales()
    other = replace(doc, fecha_inicio='2098-03-01', fecha_fin='2098-03-31')
    with pytest.raises(ValueError, match='conflict'):
        db.guardar_pdf_documental(SHA, 'package.pdf', [(1, other), (2, replace(doc, categoria='changed'))])
    assert db.obtener_versiones_documentales() == before
    assert len(db.obtener_periodos_documentales()) == 1


def test_twenty_seven_single_version_periods_stay_unresolved(db, doc):
    for index in range(27):
        year, month = 2090 + index // 12, index % 12 + 1
        partial = replace(doc, fecha_inicio=f'{year}-{month:02d}-01', fecha_fin=f'{year}-{month:02d}-07')
        db.guardar_version_documental(partial, SHA, index + 1, 'package.pdf')
    periods = db.obtener_periodos_documentales()
    assert len(periods) == 27
    assert all(p['resolution_status'] == 'UNRESOLVED' for p in periods)
    assert all(len(db.obtener_versiones_de_periodo(p['period_key'])) == 1 for p in periods)
    assert db.obtener_todos() == []


def test_invalid_payload_rolls_back(db, doc):
    with pytest.raises(ValueError):
        db.guardar_pdf_documental(SHA, 'package.pdf', [(1, doc), (2, replace(doc, total_devengado=float('nan')))])
    assert db.obtener_versiones_documentales() == []
    assert db.obtener_periodos_documentales() == []


def test_new_schema_is_additive_for_existing_economic_table(tmp_path):
    path = str(tmp_path / 'legacy.sqlite')
    db = DatabaseService(path)
    db.init_db()
    old = Nomina(id='legacy', anio=2099, mes=1, periodo='2099-01', empresa='Synthetic', cif='TEST')
    db.guardar_documento(old)
    before = db.obtener_todos()
    # Reproduce an existing database without documentary tables.
    execute(db, 'DROP TABLE payroll_document_versions')
    execute(db, 'DROP TABLE payroll_periods')
    db.init_db()
    assert db.obtener_todos() == before
    assert db.obtener_periodos_documentales() == []


@pytest.mark.parametrize('cif', ['b05366117', ' B 05366117 '])
def test_economic_guard_rejects_equivalent_cif_formatting(db, doc, cif):
    with pytest.raises(ValueError, match='ALTEN.*documental'):
        db.guardar_documento(replace(doc, cif=cif))
    assert db.obtener_todos() == []
