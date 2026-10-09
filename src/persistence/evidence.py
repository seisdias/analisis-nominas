"""Explicit SQL adapter for canonical physical evidence; no payroll dependencies."""

import sqlite3
from contextlib import contextmanager
from dataclasses import fields, replace
from enum import StrEnum
from typing import Any, Iterator, TypeVar

from src.canonical.documents import DocumentVersion, Extraction, LogicalDocument, VersionPage
from src.canonical.evidence import (
    Corpus,
    Employer,
    FileLocation,
    IngestItem,
    IngestRun,
    Person,
    SourceFile,
)
from src.canonical.facts import DocumentaryFact, FactPage, FactPageReference
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState

Record = (Person | Employer | Corpus | SourceFile | FileLocation | IngestRun | IngestItem
          | LogicalDocument | DocumentVersion | VersionPage | Extraction)
T = TypeVar('T', Person, Employer, Corpus, SourceFile, FileLocation, IngestRun, IngestItem,
            LogicalDocument, DocumentVersion, VersionPage, Extraction)
_TABLES: dict[type[Record], tuple[str, tuple[str, ...]]] = {
    Person: ('persons', ('person_id',)), Employer: ('employers', ('employer_id',)),
    Corpus: ('corpora', ('corpus_id',)), SourceFile: ('source_files', ('file_id',)),
    FileLocation: ('file_locations', ('corpus_id', 'relative_path', 'file_id')),
    IngestRun: ('ingest_runs', ('run_id',)), IngestItem: ('ingest_items', ('run_id', 'item_key')),
    LogicalDocument: ('logical_documents', ('document_id',)),
    DocumentVersion: ('document_versions', ('version_id',)),
    VersionPage: ('version_pages', ('version_id', 'ordinal')),
    Extraction: ('extractions', ('extraction_id',)),
}


class WriteOutcome(StrEnum):
    CREATED = 'created'
    IDENTICAL = 'identical'
    UPDATED = 'updated'


class EvidenceRepository:
    """Connection is infrastructure-only; methods consume/return pure records.

    Registrations are immutable. Explicit inventory updates are pending -> terminal;
    retry plans need a new plan identity. Compound operations use transaction().
    Conflict is expressed by ReproducibilityConflict, never a destructive upsert.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._sequence = 0
        if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
            raise ValueError('Evidence repository requires foreign keys enabled')

    @contextmanager
    def transaction(self) -> Iterator[None]:
        # A SAVEPOINT composes with callers' transactions, including nested units.
        self._sequence += 1
        name = f'evidence_{self._sequence}'
        self._connection.execute(f'SAVEPOINT {name}')
        try:
            yield
            self._connection.execute(f'RELEASE {name}')
        except BaseException:
            self._connection.execute(f'ROLLBACK TO {name}')
            self._connection.execute(f'RELEASE {name}')
            raise

    def _get(self, kind: type[T], *keys: str | int) -> T | None:
        table, key_names = _TABLES[kind]
        columns = ', '.join(f.name for f in fields(kind))
        where = ' AND '.join(f'{name}=?' for name in key_names)
        row = self._connection.execute(f'SELECT {columns} FROM {table} WHERE {where}', keys).fetchone()
        return kind(*row) if row is not None else None

    def _register(self, record: T) -> WriteOutcome:
        kind = type(record)
        table, key_names = _TABLES[kind]
        columns = [f.name for f in fields(record)]
        with self.transaction():
            old = self._get(kind, *(getattr(record, name) for name in key_names))
            ignored = {'created_at', 'first_seen_at', 'started_at'}
            if isinstance(record, IngestRun):
                ignored |= {'status', 'finished_at'}
            if old is not None:
                if any(getattr(old, c) != getattr(record, c) for c in columns if c not in ignored):
                    raise ReproducibilityConflict(f'Conflicting {table} identity')
                return WriteOutcome.IDENTICAL
            try:
                self._connection.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    tuple(getattr(record, c) for c in columns),
                )
            except sqlite3.IntegrityError as error:
                # Secondary uniqueness is also a reproducibility conflict. FK/CHECK
                # violations remain integrity errors; they do not assert identity.
                if error.sqlite_errorcode in (sqlite3.SQLITE_CONSTRAINT_UNIQUE, sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY):
                    raise ReproducibilityConflict(f'Conflicting {table} unique identity') from error
                raise
        return WriteOutcome.CREATED

    def register_person(self, person: Person) -> WriteOutcome:
        return self._register(person)

    def get_person(self, person_id: str) -> Person | None:
        return self._get(Person, person_id)

    def register_employer(self, employer: Employer) -> WriteOutcome:
        return self._register(employer)

    def get_employer(self, employer_id: str) -> Employer | None:
        return self._get(Employer, employer_id)

    def register_corpus(self, corpus: Corpus) -> WriteOutcome:
        return self._register(corpus)

    def get_corpus(self, corpus_id: str) -> Corpus | None:
        return self._get(Corpus, corpus_id)

    def register_source_file(self, file: SourceFile) -> WriteOutcome:
        return self._register(file)

    def get_source_file(self, file_id: str) -> SourceFile | None:
        return self._get(SourceFile, file_id)

    def register_location(self, location: FileLocation) -> WriteOutcome:
        return self._register(location)

    def get_location(self, corpus_id: str, relative_path: str, file_id: str) -> FileLocation | None:
        return self._get(FileLocation, corpus_id, relative_path, file_id)

    def create_run(self, run: IngestRun) -> WriteOutcome:
        if run.status != 'running':
            raise ValueError('New run must start running')
        return self._register(run)

    def get_run(self, run_id: str) -> IngestRun | None:
        return self._get(IngestRun, run_id)

    def register_item(self, item: IngestItem) -> WriteOutcome:
        with self.transaction():
            self._check_item(item)
            run = self.get_run(item.run_id)
            if (run is not None and run.status != 'running'
                    and self.get_item(item.run_id, item.item_key) is None):
                raise ReproducibilityConflict('Finished run cannot gain inventory items')
            return self._register(item)

    def get_item(self, run_id: str, item_key: str) -> IngestItem | None:
        return self._get(IngestItem, run_id, item_key)

    def _check_item(self, item: IngestItem) -> None:
        if item.file_id is not None and item.expected_sha256 is not None:
            file = self.get_source_file(item.file_id)
            if file is not None and file.sha256 != item.expected_sha256:
                raise ReproducibilityConflict('Item file differs from expected SHA256')

    def update_item(self, item: IngestItem) -> WriteOutcome:
        with self.transaction():
            old = self.get_item(item.run_id, item.item_key)
            if old is None:
                raise KeyError('Unknown ingest item')
            self._check_item(item)
            if old == item:
                return WriteOutcome.IDENTICAL
            mutable = {'file_id', 'status', 'reason_code', 'error_detail'}
            if any(getattr(old, f.name) != getattr(item, f.name) for f in fields(item) if f.name not in mutable):
                raise ReproducibilityConflict('Item evidence identity cannot change')
            run = self.get_run(item.run_id)
            if old.status != 'pending' or run is None or run.status != 'running':
                raise ReproducibilityConflict('Terminal inventory cannot be overwritten')
            if old.file_id is not None and old.file_id != item.file_id:
                raise ReproducibilityConflict('Existing file link cannot change')
            self._connection.execute(
                'UPDATE ingest_items SET file_id=?, status=?, reason_code=?, error_detail=? WHERE run_id=? AND item_key=?',
                (item.file_id, item.status, item.reason_code, item.error_detail, item.run_id, item.item_key),
            )
            return WriteOutcome.UPDATED

    def finish_run(self, run_id: str, status: str, finished_at: str) -> WriteOutcome:
        with self.transaction():
            old = self.get_run(run_id)
            if old is None:
                raise KeyError('Unknown ingest run')
            new = replace(old, status=status, finished_at=finished_at)
            if old.status == new.status and old.finished_at is not None:
                return WriteOutcome.IDENTICAL
            if old.status != 'running':
                raise ReproducibilityConflict('Finished run cannot change')
            statuses = [r[0] for r in self._connection.execute('SELECT status FROM ingest_items WHERE run_id=?', (run_id,))]
            if status == 'complete' and any(s in ('pending', 'failed') for s in statuses):
                raise ValueError('Complete run cannot contain pending or failed items')
            self._connection.execute('UPDATE ingest_runs SET status=?, finished_at=? WHERE run_id=?',
                                     (new.status, new.finished_at, run_id))
            return WriteOutcome.UPDATED

    def register_document(self, document: LogicalDocument) -> WriteOutcome:
        return self._register(document)

    def get_document(self, document_id: str) -> LogicalDocument | None:
        return self._get(LogicalDocument, document_id)

    def register_version(self, version: DocumentVersion) -> WriteOutcome:
        return self._register(version)

    def get_version(self, version_id: str) -> DocumentVersion | None:
        return self._get(DocumentVersion, version_id)

    def get_document_versions(self, document_id: str) -> tuple[DocumentVersion, ...]:
        """Enumerate every stored version, without selecting or interpreting one."""
        rows = self._connection.execute(
            'SELECT version_id, document_id, file_id, segment_key, created_at '
            'FROM document_versions WHERE document_id=? ORDER BY version_id', (document_id,),
        ).fetchall()
        return tuple(DocumentVersion(*row) for row in rows)

    def associate_page(self, page: VersionPage) -> WriteOutcome:
        with self.transaction():
            extent = self._connection.execute(
                'SELECT f.page_count FROM document_versions v JOIN source_files f '
                'ON f.file_id=v.file_id WHERE v.version_id=?', (page.version_id,),
            ).fetchone()
            if extent is not None and extent[0] is not None and page.page_number > extent[0]:
                raise ValueError('Page exceeds known physical file extent')
            return self._register(page)

    def get_version_pages(self, version_id: str) -> tuple[VersionPage, ...]:
        rows = self._connection.execute(
            'SELECT version_id, page_number, ordinal FROM version_pages '
            'WHERE version_id=? ORDER BY ordinal', (version_id,),
        ).fetchall()
        return tuple(VersionPage(*row) for row in rows)

    def register_extraction(self, extraction: Extraction) -> WriteOutcome:
        return self._register(extraction)

    def get_extraction(self, extraction_id: str) -> Extraction | None:
        return self._get(Extraction, extraction_id)

    def register_fact(self, fact: DocumentaryFact) -> WriteOutcome:
        with self.transaction():
            old = self.get_fact(fact.fact_id)
            if old is not None:
                if replace(fact, created_at=old.created_at) != old:
                    raise ReproducibilityConflict('Conflicting documentary fact identity')
                return WriteOutcome.IDENTICAL
            value = fact.value
            number = value.value if isinstance(value.value, ExactDecimal) else None
            text = value.value if isinstance(value.value, str) else None
            kind = 'decimal' if number is not None else 'text' if text is not None else None
            try:
                self._connection.execute(
                    'INSERT INTO documentary_facts (' + _FACT_COLUMNS + ') VALUES ('
                    + ', '.join('?' for _ in range(11)) + ')',
                    (fact.fact_id, fact.extraction_id, fact.fact_key, value.state.value, kind,
                     number.coefficient if number is not None else None,
                     number.scale if number is not None else None, text,
                     value.currency.code if value.currency is not None else None,
                     value.reason_code, fact.created_at),
                )
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode in (sqlite3.SQLITE_CONSTRAINT_UNIQUE,
                                               sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY):
                    raise ReproducibilityConflict('Conflicting documentary fact key') from error
                raise
            return WriteOutcome.CREATED

    def get_fact(self, fact_id: str) -> DocumentaryFact | None:
        row = self._connection.execute(
            'SELECT ' + _FACT_COLUMNS + ' FROM documentary_facts WHERE fact_id=?', (fact_id,),
        ).fetchone()
        return _decode_fact(row) if row is not None else None

    def get_extraction_facts(self, extraction_id: str) -> tuple[DocumentaryFact, ...]:
        rows = self._connection.execute(
            'SELECT ' + _FACT_COLUMNS + ' FROM documentary_facts '
            'WHERE extraction_id=? ORDER BY fact_key', (extraction_id,),
        ).fetchall()
        return tuple(_decode_fact(row) for row in rows)

    def associate_fact_page(self, page: FactPage) -> WriteOutcome:
        with self.transaction():
            source = self._connection.execute(
                'SELECT e.version_id FROM documentary_facts f JOIN extractions e '
                'ON e.extraction_id=f.extraction_id WHERE f.fact_id=?', (page.fact_id,),
            ).fetchone()
            if source is None:
                raise KeyError('Unknown documentary fact')
            version_id = source[0]
            known = self._connection.execute(
                'SELECT 1 FROM version_pages WHERE version_id=? AND page_number=?',
                (version_id, page.page_number),
            ).fetchone()
            if known is None:
                raise ValueError('Fact page must already be known in its source version')
            old = self._connection.execute(
                'SELECT version_id FROM fact_pages WHERE fact_id=? AND page_number=?',
                (page.fact_id, page.page_number),
            ).fetchone()
            if old is not None:
                if old[0] != version_id:
                    raise ReproducibilityConflict('Fact page belongs to a different version')
                return WriteOutcome.IDENTICAL
            self._connection.execute(
                'INSERT INTO fact_pages (fact_id, version_id, page_number) VALUES (?, ?, ?)',
                (page.fact_id, version_id, page.page_number),
            )
            return WriteOutcome.CREATED

    def get_fact_pages(self, fact_id: str) -> tuple[FactPage, ...]:
        rows = self._connection.execute(
            'SELECT fact_id, page_number FROM fact_pages WHERE fact_id=? ORDER BY page_number',
            (fact_id,),
        ).fetchall()
        return tuple(FactPage(*row) for row in rows)

    def get_fact_page_references(self, fact_id: str) -> tuple[FactPageReference, ...]:
        """Read stored version IDs without inferring them from the extraction."""
        rows = self._connection.execute(
            'SELECT fact_id, version_id, page_number FROM fact_pages '
            'WHERE fact_id=? ORDER BY page_number', (fact_id,),
        ).fetchall()
        return tuple(FactPageReference(*row) for row in rows)


_FACT_COLUMNS = ('fact_id, extraction_id, fact_key, value_state, value_kind, coefficient, '
                 'scale, text_value, currency, reason_code, created_at')


def _decode_fact(row: tuple[Any, ...]) -> DocumentaryFact:
    (identity, extraction, key, state, kind, coefficient, scale, text, currency,
     reason, created_at) = row
    value = ExactDecimal(coefficient, scale) if kind == 'decimal' else text
    return DocumentaryFact(identity, extraction, key, CanonicalValue(
        state=ValueState(state), value=value,
        currency=CurrencyCode(currency) if currency is not None else None, reason_code=reason,
    ), created_at)
