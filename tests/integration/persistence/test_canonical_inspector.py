"""Synthetic developer inspection only; no private corpus."""
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import click
import pytest
from click.testing import CliRunner

from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.evidence import Corpus, Person, SourceFile, corpus_id, person_id, source_file_id
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.canonical_inspector import cli
from src.economic_mapping import evaluate_direct_totals
from src.persistence import open_database
from src.persistence.economics import EconomicRepository


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / 'canonical.sqlite'
    with open_database(path, mode='create') as db:
        repo = EconomicRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'v1')
        file = SourceFile(source_file_id('a'*64), 'a'*64, 12, 'application/pdf')
        doc = LogicalDocument(document_id(corpus.corpus_id, 'unit'), corpus.corpus_id,
                              None, 'unknown', 'unit')
        ver = DocumentVersion(version_id(doc.document_id, file.file_id, 'whole'),
                              doc.document_id, file.file_id, 'whole')
        ext = Extraction(extraction_id(ver.version_id, 'synthetic', '1', 'b'*64),
                         ver.version_id, 'synthetic', '1', 'b'*64, 'c'*64)
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(file)
        repo.register_document(doc)
        repo.register_version(ver)
        repo.register_extraction(ext)
        facts = tuple(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(key,
            CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(20153, 2))))
            for key in ('nomina.total_devengado', 'nomina.liquido_percibir'))
        for fact in facts:
            repo.register_fact(fact)
        result = evaluate_direct_totals(doc.document_id, facts)
        repo.register_rule(result.rule)
        repo.register_assessment(result.assessment)
        for item in result.observations:
            repo.register_observation(item.observation, item.fact_ids)
        blocked = replace(result.observations[0].observation,
                          magnitude='unsupported_diagnostic')
        # A second extraction is unnecessary: unsupported magnitude is a pure diagnosis.
        from src.canonical.economics import observation_id
        blocked = replace(blocked, observation_key='unsupported',
            observation_id=observation_id(blocked.assessment_id, 'unsupported'))
        repo.register_observation(blocked, result.observations[0].fact_ids)
    return path, doc, result.observations[0].observation, blocked, facts


def invoke(dataset, *args):
    return CliRunner().invoke(cli, ['--db', str(dataset[0]), *args])


def test_help_needs_no_database():
    result = CliRunner().invoke(cli, ['--help'])
    assert result.exit_code == 0
    for command in ('summary', 'observations', 'explain', 'facts', 'document'):
        assert command in result.output


def test_summary(dataset):
    result = invoke(dataset, 'summary')
    assert result.exit_code == 0, result.output
    assert 'logical_documents: 1' in result.output
    assert 'economic_observations: 3' in result.output
    assert 'evidence_only: 3' in result.output


def test_observations_filters_and_limit(dataset):
    result = invoke(dataset, 'observations', '--magnitude', 'documentary_net',
                    '--economic-status', 'usable', '--eligibility', 'evidence_only', '--limit', '1')
    assert result.exit_code == 0, result.output
    assert 'documentary_net' in result.output
    assert 'documentary_gross' not in result.output
    assert '201.53' in result.output


def test_explain_reuses_certification_and_preserves_unknown_context(dataset, monkeypatch):
    import src.canonical_inspection as module
    original = module.certify_observation
    calls = []
    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'certify_observation', spy)
    result = invoke(dataset, 'explain', dataset[2].observation_id)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert 'certified' in result.output
    assert 'NOT_EVALUATED' in result.output
    assert 'certification != additivity' in result.output
    assert dataset[1].document_id in result.output
    assert dataset[4][0].extraction_id in result.output
    assert 'a'*64 in result.output


def test_explain_blocked_reason(dataset):
    result = invoke(dataset, 'explain', dataset[3].observation_id)
    assert result.exit_code == 0, result.output
    assert 'blocked' in result.output
    assert 'magnitude.unsupported' in result.output


def test_explain_explicit_context_requirement(dataset):
    result = invoke(dataset, 'explain', dataset[2].observation_id, '--require-currency')
    assert result.exit_code == 0, result.output
    assert 'context.currency_unknown' in result.output


def test_facts_filter(dataset):
    result = invoke(dataset, 'facts', '--fact-key', 'nomina.total_devengado', '--limit', '1')
    assert result.exit_code == 0, result.output
    assert 'nomina.total_devengado' in result.output
    assert 'nomina.liquido_percibir' not in result.output


def test_document_trace(dataset):
    result = invoke(dataset, 'document', dataset[1].document_id)
    assert result.exit_code == 0, result.output
    assert 'whole' in result.output
    assert 'a'*64 in result.output
    assert dataset[4][0].extraction_id in result.output


@pytest.mark.parametrize('command', ['explain', 'document'])
def test_missing_id(dataset, command):
    result = invoke(dataset, command, 'missing')
    assert result.exit_code != 0
    assert 'not found' in result.output.lower()


@pytest.mark.parametrize('existing', [True, False])
def test_invalid_database_does_not_create_or_modify(tmp_path, existing):
    path = tmp_path / 'invalid.sqlite'
    if existing:
        path.write_bytes(b'not SQLite')
    result = CliRunner().invoke(cli, ['--db', str(path), 'summary'])
    assert result.exit_code != 0
    assert 'Error:' in result.output
    assert path.exists() == existing
    if existing:
        assert path.read_bytes() == b'not SQLite'


def test_read_only_all_commands_and_determinism(dataset, monkeypatch):
    import src.canonical_inspection as module
    original = module.connect
    @contextmanager
    def guarded(*args, **kwargs):
        assert kwargs['mode'] == 'read_only'
        with original(*args, **kwargs) as conn:
            assert conn.execute('PRAGMA query_only').fetchone() == (1,)
            # Prove mode=ro itself prevents writes even without query_only.
            conn.execute('PRAGMA query_only=OFF')
            with pytest.raises(sqlite3.OperationalError):
                conn.execute('CREATE TABLE forbidden(x)')
            conn.execute('PRAGMA query_only=ON')
            writes = []
            def authorize(action, arg1, arg2, database, trigger):
                if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                              sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
                              sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH):
                    writes.append(action)
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            yield conn
            assert writes == []
    monkeypatch.setattr(module, 'connect', guarded)
    before = dataset[0].read_bytes()
    files = set(dataset[0].parent.iterdir())
    for args in [('summary',), ('observations',), ('facts',),
                 ('document', dataset[1].document_id), ('explain', dataset[2].observation_id)]:
        first, second = invoke(dataset, *args), invoke(dataset, *args)
        assert first.exit_code == second.exit_code == 0, first.output
        assert first.output == second.output
    assert dataset[0].read_bytes() == before
    assert set(dataset[0].parent.iterdir()) == files


def test_filters_are_parameters_not_sql(dataset):
    result = invoke(dataset, 'observations', '--magnitude', "' OR 1=1 --")
    assert result.exit_code == 0
    assert '(none)' in result.output


def test_invalid_limit(dataset):
    result = invoke(dataset, 'facts', '--limit', '0')
    assert result.exit_code != 0


def test_old_schema_is_not_migrated(tmp_path):
    from src.persistence import load_migrations
    path = tmp_path / 'v7.sqlite'
    with open_database(path, mode='create', migrations=load_migrations()[:7]):
        pass
    before = path.read_bytes()
    result = CliRunner().invoke(cli, ['--db', str(path), 'summary'])
    assert result.exit_code != 0
    assert 'v8' in result.output
    assert path.read_bytes() == before


def test_wal_refused_without_creating_sidecars(dataset):
    with sqlite3.connect(dataset[0]) as conn:
        assert conn.execute('PRAGMA journal_mode=WAL').fetchone() == ('wal',)
    before = {p.name: p.read_bytes() for p in dataset[0].parent.iterdir() if p.is_file()}
    result = invoke(dataset, 'summary')
    assert result.exit_code != 0
    assert 'WAL unsupported' in result.output
    assert {p.name: p.read_bytes() for p in dataset[0].parent.iterdir() if p.is_file()} == before


def test_renderer_escapes_documentary_control_characters():
    from src.canonical_inspector import _render
    @click.command()
    def render():
        _render({'text': '\x1b[2J\nforged row'})
    result = CliRunner().invoke(render)
    assert result.exit_code == 0
    assert '\x1b' not in result.output
    assert '\\u001b' in result.output
    assert '\\n' in result.output
