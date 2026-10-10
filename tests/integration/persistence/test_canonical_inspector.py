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
    for args in [('coverage',), ('summary',), ('observations',), ('facts',),
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


def test_coverage_counts_without_candidate_selection(dataset):
    from src.canonical_inspection import open_inspector
    with open_inspector(dataset[0]) as inspector:
        report = inspector.coverage()
    total = report['total']
    assert total['documents'] == 1
    assert total['observations'] == 3
    assert total['documentary_gross']['certified_observations'] == 1
    assert total['documentary_net']['certified_documents'] == 1
    assert total['eligibility'] == {'evidence_only': 3}
    assert total['known_liquidation_periods'] == 0
    assert total['documents_without_known_liquidation_period'] == 1
    assert 'NO DISPONIBLE' in report['concept_usability']
    result = invoke(dataset, 'coverage')
    assert result.exit_code == 0, result.output
    assert 'certified != candidate != additive' in result.output


def test_coverage_empty_database(tmp_path):
    from src.canonical_inspection import open_inspector
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    with open_inspector(path) as inspector:
        report = inspector.coverage()
    assert report['total']['documents'] == 0
    assert report['companies'] == []


@pytest.mark.parametrize('state', [ValueState.PRESENT, ValueState.UNKNOWN,
                                  ValueState.UNRELIABLE, ValueState.NOT_PRESENT])
def test_coverage_zero_and_absence(dataset, state):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        # Build fresh facts/interpretation in a second extraction, via existing APIs.
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        old = repo.get_extraction(dataset[4][0].extraction_id)
        assert old is not None
        ext = replace(old, extractor_revision='zero-state',
                      extraction_id=extraction_id(old.version_id, 'synthetic', 'zero-state', 'b'*64))
        repo.register_extraction(ext)
        value = CanonicalValue(state=state,
            value=ExactDecimal(0, 0) if state in (ValueState.PRESENT, ValueState.UNRELIABLE) else None,
            reason_code='synthetic.state')
        fact = DocumentaryFact.from_draft(ext.extraction_id, FactDraft('nomina.total_devengado', value))
        repo.register_fact(fact)
        net = DocumentaryFact.from_draft(ext.extraction_id, FactDraft('nomina.liquido_percibir', value))
        repo.register_fact(net)
        result = evaluate_direct_totals(dataset[1].document_id, (fact, net))
        repo.register_rule(result.rule)
        repo.register_assessment(result.assessment)
        for item in result.observations:
            repo.register_observation(item.observation, item.fact_ids)
        conn.commit()
    with open_inspector(dataset[0]) as inspector:
        gross = inspector.coverage()['total']['documentary_gross']
    assert gross['certified_observations'] == (2 if state == ValueState.PRESENT else 1)


def test_coverage_versions_relations_and_unresolved_document(dataset):
    from src.canonical.economics import Assessment
    from src.canonical.evidence import Employer, employer_id
    from src.canonical.relations import DocumentRelation
    from src.canonical_inspection import open_inspector
    from src.persistence.relations import RelationRepository
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = RelationRepository(conn)
        employer = Employer(employer_id('ES', 'SYNTHETIC'), 'ES', 'SYNTHETIC', 'ALTEN synthetic')
        repo.register_employer(employer)
        doc = LogicalDocument(document_id(dataset[1].corpus_id, 'unresolved'), dataset[1].corpus_id,
                              employer.employer_id, 'unknown', 'unresolved')
        repo.register_document(doc)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        version = repo.get_version(source.version_id)
        assert version is not None
        for segment in ('first', 'second'):
            repo.register_version(DocumentVersion(version_id(doc.document_id, version.file_id, segment),
                                  doc.document_id, version.file_id, segment))
        original = repo.get_assessment(dataset[2].assessment_id)
        assert original is not None
        repo.register_assessment(Assessment.from_facts(doc.document_id, original.rule_id, (),
                                                      'pending'))
        repo.register_document_relation(DocumentRelation.create(
            doc.document_id, dataset[1].document_id, 'duplicate_of', reason_code='synthetic.test'))
        concept = DocumentaryFact.from_draft(source.extraction_id, FactDraft(
            'nomina.conceptos.' + 'd'*64 + '.0.importe', CanonicalValue(
                state=ValueState.UNKNOWN, reason_code='synthetic.unknown')))
        repo.register_fact(concept)
        conn.commit()
    with open_inspector(dataset[0]) as inspector:
        report = inspector.coverage()
    company = next(c for c in report['companies'] if c['employer_id'] == employer.employer_id)
    assert company['documents'] == 1
    assert company['versions'] == 2
    assert company['documents_with_multiple_versions'] == 1
    assert company['observations'] == 0
    assert company['eligibility'] == {}
    assert company['assessment_states'] == {'pending': 1}
    assert company['documentary_gross']['documents_without_observation'] == 1
    assert report['total']['registered_document_relations'] == {'duplicate_of': 1}
    assert report['total']['documentary_concept_occurrences_per_extraction'] == 1
    assert report['total']['concept_amount_states'] == {'unknown': 1}


def test_coverage_explicit_periods_are_not_observation_counts(dataset):
    from src.canonical.economics import observation_id
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        old = dataset[2]
        evidence = repo.get_observation(old.observation_id)
        assert evidence is not None
        for key in ('period-a', 'period-b'):
            obs = replace(old, observation_key=key,
                          observation_id=observation_id(old.assessment_id, key),
                          liquidation_period=CanonicalValue(state=ValueState.PRESENT, value='2025-01'))
            repo.register_observation(obs, evidence.fact_ids)
        conn.commit()
    with open_inspector(dataset[0]) as inspector:
        total = inspector.coverage()['total']
    assert total['observations'] == 5
    assert total['documents'] == 1
    assert total['known_liquidation_periods'] == 1
    assert total['documents_without_known_liquidation_period'] == 0


@pytest.mark.parametrize('prefix', ['nomina.', 'payload/'])
@pytest.mark.parametrize('variant', ['coherent', 'conflict', 'missing', 'unknown', 'zero', 'invalid'])
def test_documentary_coverage_all_versions(dataset, prefix, variant):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        version = repo.get_version(source.version_id)
        assert version is not None
        other = replace(version, segment_key='other',
                        version_id=version_id(version.document_id, version.file_id, 'other'))
        repo.register_version(other)
        ext = replace(source, version_id=other.version_id,
                      extraction_id=extraction_id(other.version_id, 'synthetic', '1', 'b'*64))
        repo.register_extraction(ext)
        for index, extraction in enumerate((source, ext)):
            values: dict[str, str | ExactDecimal] = {'empresa': 'Empresa sintética', 'cif': 'SECRET_TEST_TAX_ID',
                      'anio': ExactDecimal(2025, 0), 'mes': ExactDecimal(1, 0)}
            if index and variant == 'conflict':
                values['empresa'] = 'Otra empresa'
                values['mes'] = ExactDecimal(2, 0)
            if index and variant in ('zero', 'invalid'):
                values['mes'] = ExactDecimal(0 if variant == 'zero' else 13, 0)
            for key, value in values.items():
                if index and variant == 'missing' and key == 'empresa':
                    continue
                canonical = CanonicalValue(state=ValueState.PRESENT, value=value)
                if index and variant == 'unknown' and key == 'empresa':
                    canonical = CanonicalValue(state=ValueState.UNKNOWN)
                repo.register_fact(DocumentaryFact.from_draft(
                    extraction.extraction_id, FactDraft(prefix + key, canonical)))
        conn.commit()
    before = dataset[0].read_bytes()
    with open_inspector(dataset[0]) as inspector:
        report = inspector.coverage()
    total = report['total']['documentary_context']
    assert total['cif']['known_documents'] == 1
    assert total['company']['known_documents'] == int(variant not in ('conflict', 'missing', 'unknown'))
    assert total['year_month']['known_documents'] == int(variant not in ('conflict', 'zero', 'invalid'))
    group = report['documentary_companies'][0]
    assert group['company_text'] == ('Empresa sintética'
        if variant not in ('conflict', 'missing', 'unknown') else None)
    if variant == 'conflict':
        assert total['company']['diagnostics'] == {'conflicting_values': 1}
    if variant == 'unknown':
        assert total['company']['diagnostics'] == {'non_present.unknown': 1}
    result = invoke(dataset, 'coverage')
    assert result.exit_code == 0
    assert 'SECRET_TEST_TAX_ID' not in result.output
    assert dataset[0].read_bytes() == before
    assert report['total']['known_liquidation_periods'] == 0


def test_documentary_coverage_version_without_extraction(dataset):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        version = repo.get_version(source.version_id)
        assert version is not None
        repo.register_version(replace(version, segment_key='unextracted',
            version_id=version_id(version.document_id, version.file_id, 'unextracted')))
        conn.commit()
    with open_inspector(dataset[0]) as inspector:
        report = inspector.coverage()
    field = report['total']['documentary_context']['company']
    assert field['known_documents'] == 0
    assert field['diagnostics'] == {'missing_extraction': 1, 'missing_fact': 1}
    assert report['documentary_companies'][0]['company_text'] is None


@pytest.mark.parametrize('format_name', ['ordinary', 'alten'])
def test_coverage_documentary_formats_preserve_extraction_counts(dataset, format_name):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        original = repo.get_version(source.version_id)
        assert original is not None
        doc = replace(dataset[1], origin_key='documentary-only',
                      document_id=document_id(dataset[1].corpus_id, 'documentary-only'))
        repo.register_document(doc)
        prefix = 'nomina.' if format_name == 'ordinary' else 'payload/'
        for index in range(2):
            segment = f'evidence-{index}'
            version = DocumentVersion(version_id(doc.document_id, original.file_id, segment),
                                      doc.document_id, original.file_id, segment)
            repo.register_version(version)
            ext = replace(source, version_id=version.version_id,
                          extraction_id=extraction_id(version.version_id, 'synthetic', '1', 'b'*64))
            repo.register_extraction(ext)
            drafts = [
                FactDraft(prefix + 'total_devengado', CanonicalValue(
                    state=ValueState.PRESENT, value=ExactDecimal(1, 0))),
                FactDraft(prefix + 'liquido_percibir', CanonicalValue(state=ValueState.UNKNOWN)),
            ]
            for occurrence in range(3):
                concept = (f'nomina.conceptos.{"d"*64}.{occurrence}.' if format_name == 'ordinary'
                           else f'payload/conceptos/{occurrence}/')
                drafts.extend(FactDraft(concept + field, CanonicalValue(
                    state=ValueState.PRESENT, value='synthetic'))
                    for field in ('codigo', 'concepto', 'categoria'))
                if occurrence != 1:  # Missing amount is not unknown or zero.
                    drafts.append(FactDraft(concept + 'importe', CanonicalValue(
                        state=ValueState.UNKNOWN if occurrence == 0 else ValueState.NOT_PRESENT)))
            # Similar prefixes are not verified concept/total paths.
            drafts.append(FactDraft(prefix + 'total_devengado_extra',
                                    CanonicalValue(state=ValueState.UNKNOWN)))
            drafts.append(FactDraft('payload/conceptos/not-an-index/importe',
                                    CanonicalValue(state=ValueState.UNKNOWN)))
            for draft in drafts:
                fact = DocumentaryFact.from_draft(ext.extraction_id, draft)
                assert repo.register_fact(fact) == 'created'
                assert repo.register_fact(fact) == 'identical'
        conn.commit()
    before = dataset[0].read_bytes()
    with open_inspector(dataset[0]) as inspector:
        report = inspector.coverage()
    total = report['total']
    assert total['documents'] == 2
    assert total['versions'] == 3
    assert total['documentary_concept_occurrences_per_extraction'] == 6
    assert total['documents_with_concept_fields'] == 1
    assert total['concept_amount_states'] == {'not_present': 2, 'unknown': 2}
    assert total['documentary_gross']['documentary_fact_states_all_extractions'] == {'present': 3}
    assert total['documentary_net']['documentary_fact_states_all_extractions'] == {'present': 1, 'unknown': 2}
    assert total['observations'] == 3  # The documentary-only versions generate none.
    assert total['documentary_gross']['certified_documents'] == 1
    assert total['eligibility'] == {'evidence_only': 3}
    assert dataset[0].read_bytes() == before
