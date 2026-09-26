"""Synthetic documentary ingestion; all SQLite paths are isolated."""
import hashlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from scripts.ingest_alten import is_certificate, main, run_ingestion
from src.extraction import ExtractedDocument, ExtractedWord
from src.services.database_service import DatabaseService
from tests.test_alten_parser import page


def certificate():
    header = 'ALTEN DELIVERY CENTER SPAIN SLU B05366117'
    texts = [f'{header}\n2097\n12.345,67 1.234,56\n321,09\n2097',
             f'{header}\n2097\n2097\n2097\nMadrid 1 enero 2098']
    first = [ExtractedWord(t, x, x+40, y, y+8, 1) for t, x, y in (
        ('2097', 500, 100), ('12.345,67', 300, 200), ('1.234,56', 500, 200),
        ('321,09', 500, 350), ('2097', 500, 700),
    )]
    second = [ExtractedWord('2097', 500, 540, y, y+8, 2) for y in (100, 400, 650)]
    pages = tuple(ExtractedDocument(t, tuple(w)) for t, w in zip(texts, (first, second), strict=True))
    return ExtractedDocument('\n'.join(texts), pages=pages)


def package():
    p = page()
    return ExtractedDocument(p.text, pages=(p,))


def test_certificate_by_structure_not_filename():
    assert is_certificate(certificate())
    assert not is_certificate(package())
    original = certificate()
    assert original.pages is not None
    for changed in (
        replace(original, pages=(original.pages[0],)),
        replace(original, pages=(replace(original.pages[0], text=original.pages[0].text + '\nPeriodo de liquidación'), original.pages[1])),
        replace(original, pages=(replace(original.pages[0], text=original.pages[0].text.replace('B05366117', 'WRONG')), original.pages[1])),
        replace(original, pages=(replace(original.pages[0], text=original.pages[0].text.replace('2097', '2096')), original.pages[1])),
        replace(original, pages=(replace(original.pages[0], words=None), original.pages[1])),
    ):
        assert not is_certificate(changed)


def test_deterministic_snapshot_dedup_and_idempotence(tmp_path):
    directory = tmp_path / 'pdfs'
    directory.mkdir()
    for name, content in [('z.pdf', b'same PDF'), ('a.PDF', b'same PDF'), ('m.pdf', b'certificate')]:
        (directory / name).write_bytes(content)
    (directory / 'ignore.txt').write_text('not a PDF')
    seen = []
    def extract(source):
        data = source.read()
        seen.append(data)
        return certificate() if data == b'certificate' else package()
    db = str(tmp_path / 'isolated.sqlite')
    with patch('scripts.ingest_alten.extract_pdf_document', side_effect=extract):
        first = run_ingestion(directory, db)
        before = DatabaseService(db).obtener_versiones_documentales()
        second = run_ingestion(directory, db)
    assert seen[:3] == [b'same PDF', b'certificate', b'same PDF']
    assert (first.found, first.payroll_pdfs, first.certificates, first.versions, first.periods, first.failed) == (3, 2, 1, 2, 1, 0)
    assert (first.new_versions, first.idempotent_versions, first.stored_versions) == (1, 1, 1)
    assert (second.new_versions, second.idempotent_versions, second.stored_versions) == (0, 2, 1)
    assert DatabaseService(db).obtener_versiones_documentales() == before
    assert before[0]['pdf_sha256'] == hashlib.sha256(b'same PDF').hexdigest()
    assert DatabaseService(db).obtener_todos() == []


def test_parse_failure_in_middle_does_not_write(tmp_path):
    directory = tmp_path / 'pdfs'
    directory.mkdir()
    (directory / 'multi.pdf').write_bytes(b'multi')
    p = page()
    invalid = ExtractedDocument('invalid payroll')
    document = ExtractedDocument('', pages=(p, invalid, p))
    db = str(tmp_path / 'isolated.sqlite')
    with patch('scripts.ingest_alten.extract_pdf_document', return_value=document):
        result = run_ingestion(directory, db)
    assert result.failed == 1 and result.versions == 0
    assert DatabaseService(db).obtener_versiones_documentales() == []
    assert DatabaseService(db).obtener_periodos_documentales() == []


@pytest.mark.parametrize('text', ['', 'unknown document', 'Certificado without evidence'])
def test_unknown_or_scan_is_real_failure(tmp_path, text):
    directory = tmp_path / 'pdfs'
    directory.mkdir()
    (directory / 'arbitrary.pdf').write_bytes(b'placeholder')
    with patch('scripts.ingest_alten.extract_pdf_document', return_value=ExtractedDocument(text)):
        assert main(['--pdf-dir', str(directory), '--db', str(tmp_path / 'isolated.sqlite')]) == 1


@pytest.mark.parametrize('argv,expected', [
    ([], {'pdf_dir': 'data/test/alten', 'db_path': 'data/runtime/nominas.sqlite'}),
    (['--pdf-dir', 'synthetic', '--db', 'isolated.sqlite'], {'pdf_dir': 'synthetic', 'db_path': 'isolated.sqlite'}),
])
def test_cli_arguments(argv, expected):
    with patch('scripts.ingest_alten.run_ingestion') as run:
        run.return_value.failed = 0
        assert main(argv) == 0
        run.assert_called_once_with(**expected)
        run.return_value.failed = 1
        assert main(argv) == 1


def test_empty_directory_does_not_create_db(tmp_path):
    db = tmp_path / 'never.sqlite'
    assert main(['--pdf-dir', str(tmp_path), '--db', str(db)]) == 1
    assert not db.exists()
