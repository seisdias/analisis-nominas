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
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.canonical_inspector import cli
from src.economic_mapping import evaluate_direct_totals
from src.persistence import open_database
from src.persistence.economics import EconomicRepository


@pytest.fixture
def dataset(tmp_path, request):
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
            CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(20153, 2),
                           currency=getattr(request, 'param', None))))
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
    for command in ('companies', 'documents', 'summary', 'observations', 'explain', 'facts', 'document'):
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
    exports = dataset[0].parent / 'exports'
    exports.mkdir()
    files = set(dataset[0].parent.iterdir())
    for args in [('companies',), ('documents',), ('documents', '--year', '2024'),
                 ('documents', '--csv', str(exports / 'documents.csv')),
                 ('coverage',), ('summary',), ('observations',), ('facts',),
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


@pytest.mark.parametrize('prefix', ['nomina.', 'payload/'])
@pytest.mark.parametrize('names', [('Empresa exacta',), ('Empresa exacta', 'Empresa exacta'),
                                  ('Empresa exacta', 'Otra empresa'), ('Empresa exacta', None)])
def test_companies_documentary_versions(dataset, prefix, names):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        original = repo.get_version(source.version_id)
        assert original is not None
        for index, name in enumerate(names):
            ext = source
            if index:
                version = replace(original, segment_key=str(index), version_id=version_id(
                    original.document_id, original.file_id, str(index)))
                repo.register_version(version)
                ext = replace(source, version_id=version.version_id, extraction_id=extraction_id(
                    version.version_id, 'synthetic', '1', 'b'*64))
                repo.register_extraction(ext)
            if name is not None:
                repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(
                    prefix + 'empresa', CanonicalValue(state=ValueState.PRESENT, value=name))))
            repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(
                prefix + 'cif', CanonicalValue(state=ValueState.PRESENT, value='SECRET_TAX_ID'))))
    with open_inspector(dataset[0]) as inspector:
        report = inspector.companies()
    coherent = len(set(names)) == 1
    assert report['companies'] == ([{'company_text': 'Empresa exacta', 'documents': 1}]
                                    if coherent else [])
    assert len(report['unassigned_documents']) == int(not coherent)
    if not coherent:
        assert report['unassigned_documents'] == [{
            'document_id': dataset[1].document_id,
            'company_texts': tuple(sorted(n for n in names if n is not None)),
            'diagnostics': ('missing_fact',) if None in names else ('conflicting_values',),
        }]
    result = invoke(dataset, 'companies')
    assert result.exit_code == 0, result.output
    assert 'Empresa exacta' in result.output
    for private in ('SECRET_TAX_ID', 'cif', '201.53', 'employer_id', 'documentary_gross'):
        assert private not in result.output


def test_companies_empty_database(tmp_path):
    from src.canonical_inspection import open_inspector
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    with open_inspector(path) as inspector:
        assert inspector.companies() == {'companies': [], 'unassigned_documents': []}
    result = CliRunner().invoke(cli, ['--db', str(path), 'companies'])
    assert result.exit_code == 0, result.output
    assert '(none)' in result.output


def test_companies_exact_grouping_and_order(dataset):
    from src.canonical.evidence import Employer, employer_id
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        employer = Employer(employer_id('ES', 'SYNTHETIC'), 'ES', 'SYNTHETIC', 'Canonical name')
        repo.register_employer(employer)
        source = repo.get_extraction(dataset[4][0].extraction_id)
        assert source is not None
        original = repo.get_version(source.version_id)
        assert original is not None
        for index, name in enumerate(('Zeta', ' Alfa ', 'Alfa', 'Alfa')):
            key = f'company-{index}'
            doc = replace(dataset[1], origin_key=key,
                          document_id=document_id(dataset[1].corpus_id, key),
                          employer_id=employer.employer_id if index != 3 else None)
            repo.register_document(doc)
            version = replace(original, document_id=doc.document_id,
                              version_id=version_id(doc.document_id, original.file_id, 'whole'))
            repo.register_version(version)
            ext = replace(source, version_id=version.version_id, extraction_id=extraction_id(
                version.version_id, 'synthetic', '1', 'b'*64))
            repo.register_extraction(ext)
            repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(
                'nomina.empresa', CanonicalValue(state=ValueState.PRESENT, value=name))))
    with open_inspector(dataset[0]) as inspector:
        report = inspector.companies()
    assert report['companies'] == [
        {'company_text': ' Alfa ', 'documents': 1},
        {'company_text': 'Alfa', 'documents': 2},
        {'company_text': 'Zeta', 'documents': 1},
    ]
    assert report['unassigned_documents'] == [{
        'document_id': dataset[1].document_id, 'company_texts': (), 'diagnostics': ('missing_fact',),
    }]


def _add_document_context(repo, extraction, company='EXCELTIC SL', year=2024, month=3,
                          prefix='nomina.'):
    for key, value in (('empresa', company), ('anio', year), ('mes', month)):
        if value is not None:
            raw = ExactDecimal(value, 0) if isinstance(value, int) else value
            repo.register_fact(DocumentaryFact.from_draft(extraction.extraction_id, FactDraft(
                prefix + key, CanonicalValue(state=ValueState.PRESENT, value=raw))))


@pytest.mark.parametrize('filters,expected', [
    ({}, 1), ({'year': 2024}, 1), ({'month': 3}, 1), ({'company': 'EXCELTIC SL'}, 1),
    ({'company': 'EXCELTIC SL', 'year': 2024, 'month': 3}, 1),
    ({'company': 'EXCELTIC SL', 'year': 2024, 'month': 4}, 0),
    ({'year': 2023}, 0), ({'company': 'exceltic sl'}, 0),
    ({'company': ' EXCELTIC SL'}, 0), ({'company': "' OR 1=1 --"}, 0),
])
def test_documents_filters_and_certified_amounts(dataset, filters, expected):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        ext = repo.get_extraction(dataset[4][0].extraction_id)
        assert ext is not None
        _add_document_context(repo, ext)
    with open_inspector(dataset[0]) as inspector:
        rows = inspector.documents(**filters)
    assert len(rows) == expected
    if rows:
        row = rows[0]
        assert row['document_id'] == dataset[1].document_id
        assert (row['company_text'], row['year'], row['month']) == ('EXCELTIC SL', 2024, 3)
        assert row['context_diagnostics'] == {'company': (), 'year': (), 'month': ()}
        for key in ('gross', 'net'):
            assert row[key] == {'status': 'certified', 'amount': ExactDecimal(20153, 2),
                                'currency': None}
    args = [arg for key, value in filters.items() for arg in ('--' + key, str(value))]
    result = invoke(dataset, 'documents', *args)
    assert result.exit_code == 0, result.output
    assert result.output.count('document_id:') == expected
    assert result.output.count('amount: 201.53') == 2 * expected


@pytest.mark.parametrize('variant', ['coherent', 'conflict', 'missing', 'unextracted'])
@pytest.mark.parametrize('same_version', [False, True])
def test_documents_context_across_versions_and_extractions(dataset, variant, same_version):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        ext = repo.get_extraction(dataset[4][0].extraction_id)
        assert ext is not None
        _add_document_context(repo, ext)
        version = repo.get_version(ext.version_id)
        assert version is not None
        if not same_version or variant == 'unextracted':
            version = replace(version, segment_key='extra', version_id=version_id(
                version.document_id, version.file_id, 'extra'))
            repo.register_version(version)
        if variant != 'unextracted':
            extra = replace(ext, version_id=version.version_id, extractor_revision='2',
                            extraction_id=extraction_id(version.version_id, 'synthetic', '2', 'b'*64))
            repo.register_extraction(extra)
            _add_document_context(repo, extra,
                company='Otra' if variant == 'conflict' else None if variant == 'missing' else 'EXCELTIC SL',
                year=2025 if variant == 'conflict' else 2024,
                month=None if variant == 'missing' else 3)
    with open_inspector(dataset[0]) as inspector:
        rows = inspector.documents()
        assert len(rows) == 1
        row = rows[0]
        assert row['company_text'] == ('EXCELTIC SL' if variant == 'coherent' else None)
        assert row['year'] == (None if variant in ('conflict', 'unextracted') else 2024)
        assert row['month'] == (None if variant in ('missing', 'unextracted') else 3)
        assert bool(row['context_diagnostics']['company']) == (variant != 'coherent')
        assert len(inspector.documents(company='EXCELTIC SL')) == int(variant == 'coherent')
        assert len(inspector.documents(year=2024)) == int(variant in ('coherent', 'missing'))
        assert len(inspector.documents(month=3)) == int(variant in ('coherent', 'conflict'))
        if variant == 'conflict':
            assert row['context_diagnostics']['company'] == ('conflicting_values',)
            assert row['context_diagnostics']['year'] == ('conflicting_values',)
        # A unique certified observation retains its document link; no version is selected.
        assert row['gross']['amount'] == ExactDecimal(20153, 2)


@pytest.mark.parametrize('variant', ['duplicate', 'conflicting', 'blocked', 'mixed', 'zero'])
def test_documents_amount_availability(dataset, variant):
    from src.canonical.economics import observation_id
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        old = dataset[2]
        evidence = repo.get_observation(old.observation_id)
        assert evidence is not None
        if variant == 'blocked':
            # Synthetic corruption: PRESENT documentary facts must not rescue a blocked observation.
            conn.execute("UPDATE economic_observations SET economic_status='pending' "
                         'WHERE observation_id=?', (old.observation_id,))
        elif variant in ('duplicate', 'mixed'):
            new = replace(old, observation_key='other',
                          observation_id=observation_id(old.assessment_id, 'other'),
                          economic_status='pending' if variant == 'mixed' else old.economic_status)
            repo.register_observation(new, evidence.fact_ids)
        else:
            ext = repo.get_extraction(dataset[4][0].extraction_id)
            assert ext is not None
            extra = replace(ext, extractor_revision='2',
                            extraction_id=extraction_id(ext.version_id, 'synthetic', '2', 'b'*64))
            repo.register_extraction(extra)
            facts = tuple(DocumentaryFact.from_draft(extra.extraction_id, FactDraft(key,
                CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(0 if variant == 'zero' else 777, 0))))
                for key in ('nomina.total_devengado', 'nomina.liquido_percibir'))
            for fact in facts:
                repo.register_fact(fact)
            mapped = evaluate_direct_totals(dataset[1].document_id, facts)
            repo.register_rule(mapped.rule)
            repo.register_assessment(mapped.assessment)
            if variant == 'zero':
                conn.execute('DELETE FROM observation_facts')
                conn.execute('DELETE FROM economic_observations')
            for item in mapped.observations:
                repo.register_observation(item.observation, item.fact_ids)
    with open_inspector(dataset[0]) as inspector:
        row = inspector.documents()[0]
    # dataset[2] may be net or gross: check its actual magnitude.
    target = 'gross' if dataset[2].magnitude == 'documentary_gross' else 'net'
    if variant == 'zero':
        assert row[target]['status'] == 'certified'
        assert row[target]['amount'] == ExactDecimal(0, 0)
    else:
        assert row[target]['status'] == ('not_certified' if variant == 'blocked' else 'ambiguous')
        assert 'amount' not in row[target]
    result = invoke(dataset, 'documents')
    assert result.exit_code == 0, result.output
    if variant == 'conflicting':
        assert 'amount:' not in result.output
        assert '777' not in result.output


def test_documents_alten_facts_without_observations(dataset):
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        ext = repo.get_extraction(dataset[4][0].extraction_id)
        assert ext is not None
        _add_document_context(repo, ext, company='ALTEN', prefix='payload/')
        for key in ('total_devengado', 'liquido_percibir'):
            repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(
                'payload/' + key, CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(99999, 2)))))
        conn.execute('DELETE FROM observation_facts')
        conn.execute('DELETE FROM economic_observations')
    with open_inspector(dataset[0]) as inspector:
        row = inspector.documents(company='ALTEN', year=2024, month=3)[0]
    assert row['gross'] == row['net'] == {'status': 'no_observation'}
    result = invoke(dataset, 'documents')
    assert result.exit_code == 0, result.output
    assert 'amount:' not in result.output
    assert '999.99' not in result.output


def test_documents_empty_database(tmp_path):
    from src.canonical_inspection import open_inspector
    path = tmp_path / 'empty.sqlite'
    with open_database(path, mode='create'):
        pass
    with open_inspector(path) as inspector:
        assert inspector.documents() == []
    result = CliRunner().invoke(cli, ['--db', str(path), 'documents'])
    assert result.exit_code == 0, result.output
    assert result.output == '(none)\n'


@pytest.mark.parametrize('option,value', [('--month', '0'), ('--month', '13'),
                                        ('--month', '1.5'), ('--year', '0'), ('--year', '10000')])
def test_documents_invalid_filters(dataset, option, value):
    result = invoke(dataset, 'documents', option, value)
    assert result.exit_code != 0
    assert 'Invalid value' in result.output


@pytest.mark.parametrize('variant', ['wrong_value', 'wrong_support', 'multiple_extractions'])
def test_documents_require_certified_support(dataset, variant):
    from src.canonical.economics import observation_id
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        old = dataset[2]
        evidence = repo.get_observation(old.observation_id)
        assert evidence is not None
        conn.execute('DELETE FROM observation_facts WHERE observation_id=?', (old.observation_id,))
        conn.execute('DELETE FROM economic_observations WHERE observation_id=?', (old.observation_id,))
        if variant == 'multiple_extractions':
            ext = repo.get_extraction(dataset[4][0].extraction_id)
            assert ext is not None
            extra = replace(ext, extractor_revision='2',
                            extraction_id=extraction_id(ext.version_id, 'synthetic', '2', 'b'*64))
            repo.register_extraction(extra)
            fact = DocumentaryFact.from_draft(extra.extraction_id, FactDraft('nomina.empresa',
                CanonicalValue(state=ValueState.PRESENT, value='EXCELTIC SL')))
            repo.register_fact(fact)
            mapped = evaluate_direct_totals(dataset[1].document_id, (*dataset[4], fact))
            repo.register_rule(mapped.rule)
            repo.register_assessment(mapped.assessment)
            new = replace(old, assessment_id=mapped.assessment.assessment_id,
                          observation_id=observation_id(mapped.assessment.assessment_id, old.observation_key))
        else:
            new = replace(old, value=CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(999, 0)))
        support = (next(f.fact_id for f in dataset[4] if f.fact_id not in evidence.fact_ids),)
        repo.register_observation(old if variant == 'wrong_support' else new,
                                  support if variant == 'wrong_support' else evidence.fact_ids)
    with open_inspector(dataset[0]) as inspector:
        row = inspector.documents()[0]
    target = 'gross' if old.magnitude == 'documentary_gross' else 'net'
    assert row[target] == {'status': 'not_certified'}


def test_documents_privacy_order_and_missing_context(dataset):
    from src.canonical.evidence import FileLocation
    from src.canonical_inspection import open_inspector
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        ext = repo.get_extraction(dataset[4][0].extraction_id)
        assert ext is not None
        version = repo.get_version(ext.version_id)
        assert version is not None
        repo.register_location(FileLocation(dataset[1].corpus_id,
            'private/SECRET_PAYROLL.pdf', version.file_id, 'SECRET_PAYROLL.pdf'))
        repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft('nomina.cif',
            CanonicalValue(state=ValueState.PRESENT, value='SECRET_TAX_ID'))))
        for key in ('z-last', 'a-first'):
            repo.register_document(replace(dataset[1], origin_key=key,
                document_id=document_id(dataset[1].corpus_id, key)))
    with open_inspector(dataset[0]) as inspector:
        rows = inspector.documents()
    assert len(rows) == 3
    assert [r['document_id'] for r in rows] == sorted(r['document_id'] for r in rows)
    for row in rows:
        assert (row['company_text'], row['year'], row['month']) == (None, None, None)
        assert all(row['context_diagnostics'].values())
        if row['document_id'] != dataset[1].document_id:
            assert row['gross'] == row['net'] == {'status': 'no_observation'}
    result = invoke(dataset, 'documents')
    assert result.exit_code == 0, result.output
    for secret in ('SECRET', 'private/', 'cif', 'relative_path', 'original_filename', str(dataset[0])):
        assert secret not in result.output


CSV_COLUMNS = ['document_id', 'company_text', 'year', 'month', 'gross_status',
               'gross_amount', 'gross_currency', 'net_status', 'net_amount', 'net_currency']


def _read_document_csv(path):
    import csv
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle, delimiter=';')
        assert reader.fieldnames == CSV_COLUMNS
        return list(reader)


@pytest.mark.parametrize('filtered', [False, True])
def test_documents_csv_complete_and_filtered(dataset, tmp_path, filtered):
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        ext = repo.get_extraction(dataset[4][0].extraction_id)
        assert ext is not None
        _add_document_context(repo, ext, company='Árbol; "SL"\nSegunda línea')
        version = repo.get_version(ext.version_id)
        assert version is not None
        other = replace(version, segment_key='other', version_id=version_id(
            version.document_id, version.file_id, 'other'))
        repo.register_version(other)
        extra = replace(ext, version_id=other.version_id, extraction_id=extraction_id(
            other.version_id, 'synthetic', '1', 'b'*64))
        repo.register_extraction(extra)
        _add_document_context(repo, extra, company='Árbol; "SL"\nSegunda línea')
        repo.register_document(replace(dataset[1], origin_key='missing',
            document_id=document_id(dataset[1].corpus_id, 'missing')))
    before = dataset[0].read_bytes()
    target = tmp_path / 'export.csv'
    args = ('--company', 'Árbol; "SL"\nSegunda línea', '--year', '2024', '--month', '3') if filtered else ()
    result = invoke(dataset, 'documents', *args, '--csv', str(target))
    assert result.exit_code == 0, result.output
    rows = _read_document_csv(target)
    assert len(rows) == (1 if filtered else 2)
    assert [r['document_id'] for r in rows] == sorted(r['document_id'] for r in rows)
    row = next(r for r in rows if r['document_id'] == dataset[1].document_id)
    assert row == dict(zip(CSV_COLUMNS, [dataset[1].document_id, 'Árbol; "SL"\nSegunda línea',
        '2024', '3', 'certified', '201.53', '', 'certified', '201.53', ''], strict=True))
    if not filtered:
        absent = next(r for r in rows if r is not row)
        assert all(absent[k] == '' for k in ('company_text', 'year', 'month', 'gross_amount', 'net_amount'))
        assert absent['gross_status'] == absent['net_status'] == 'no_observation'
    assert dataset[0].read_bytes() == before
    original = target.read_bytes()
    assert invoke(dataset, 'documents', *args, '--csv', str(target)).exit_code == 0
    assert target.read_bytes() == original


@pytest.mark.parametrize('variant', ['alten', 'ambiguous', 'not_certified'])
def test_documents_csv_unavailable_amounts(dataset, tmp_path, variant):
    from src.canonical.economics import observation_id
    with sqlite3.connect(dataset[0]) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        repo = EconomicRepository(conn)
        if variant == 'alten':
            ext = repo.get_extraction(dataset[4][0].extraction_id)
            assert ext is not None
            _add_document_context(repo, ext, company='ALTEN', prefix='payload/')
            repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(
                'payload/total_devengado', CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(123, 0)))))
            conn.execute('DELETE FROM observation_facts')
            conn.execute('DELETE FROM economic_observations')
        elif variant == 'ambiguous':
            for magnitude in ('documentary_gross', 'documentary_net'):
                identity = conn.execute('SELECT observation_id FROM economic_observations WHERE magnitude=?',
                                        (magnitude,)).fetchone()[0]
                evidence = repo.get_observation(identity)
                assert evidence is not None
                old = evidence.observation
                repo.register_observation(replace(old, observation_key='extra-' + magnitude,
                    observation_id=observation_id(old.assessment_id, 'extra-' + magnitude)), evidence.fact_ids)
        else:
            conn.execute("UPDATE economic_observations SET economic_status='pending'")
    target = tmp_path / 'export.csv'
    result = invoke(dataset, 'documents', '--csv', str(target))
    assert result.exit_code == 0, result.output
    row, = _read_document_csv(target)
    assert row['gross_status'] == row['net_status'] == ('no_observation' if variant == 'alten' else variant)
    assert all(row[k] == '' for k in ('gross_amount', 'net_amount', 'gross_currency', 'net_currency'))


@pytest.mark.parametrize('empty_database', [False, True])
def test_documents_csv_empty(dataset, tmp_path, empty_database):
    path = dataset[0]
    if empty_database:
        path = tmp_path / 'empty.sqlite'
        with open_database(path, mode='create'):
            pass
    target = tmp_path / 'empty.csv'
    result = CliRunner().invoke(cli, ['--db', str(path), 'documents', '--year', '2000', '--csv', str(target)])
    assert result.exit_code == 0, result.output
    assert _read_document_csv(target) == []


@pytest.mark.parametrize('stage', ['create', 'write', 'replace'])
@pytest.mark.parametrize('existing', [False, True])
def test_documents_csv_atomic_failure(dataset, tmp_path, monkeypatch, stage, existing):
    import src.canonical_inspector as module
    target = tmp_path / 'export.csv'
    if existing:
        target.write_bytes(b'previous export')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    def fail(*args, **kwargs):
        raise OSError('synthetic write failure')
    if stage == 'create':
        monkeypatch.setattr(module, 'NamedTemporaryFile', fail)
    elif stage == 'replace':
        monkeypatch.setattr(module.os, 'replace', fail)
    else:
        original = module.csv.DictWriter
        def failing_writer(*args, **kwargs):
            writer = original(*args, **kwargs)
            write_row = writer.writerow
            calls = 0
            def fail_after_header(row):
                nonlocal calls
                calls += 1
                if calls > 1:
                    fail()
                return write_row(row)
            monkeypatch.setattr(writer, 'writerow', fail_after_header)
            return writer
        monkeypatch.setattr(module.csv, 'DictWriter', failing_writer)
    result = invoke(dataset, 'documents', '--csv', str(target))
    assert result.exit_code != 0
    assert 'Error:' in result.output
    assert 'synthetic write failure' in result.output
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('alias', ['direct', 'symlink', 'hardlink'])
def test_documents_csv_cannot_replace_database(dataset, tmp_path, alias):
    target = dataset[0] if alias == 'direct' else tmp_path / 'alias.csv'
    if alias == 'symlink':
        target.symlink_to(dataset[0])
    if alias == 'hardlink':
        target.hardlink_to(dataset[0])
    before = dataset[0].read_bytes()
    result = invoke(dataset, 'documents', '--csv', str(target))
    assert result.exit_code != 0
    assert 'Error:' in result.output
    assert 'must not be the SQLite database' in result.output
    assert target.read_bytes() == dataset[0].read_bytes() == before


def test_documents_csv_zero_currency_and_certification_guard(dataset, tmp_path, monkeypatch):
    from src.canonical_inspection import CanonicalInspector
    def query(self, **filters):
        assert filters == {'company': 'Exact', 'year': 2024, 'month': 3}
        return [{'document_id': 'synthetic', 'company_text': 'Exact', 'year': 2024, 'month': 3,
                 'gross': {'status': 'certified', 'amount': ExactDecimal(0, 2), 'currency': CurrencyCode('EUR')},
                 'net': {'status': 'not_certified', 'amount': ExactDecimal(999, 0), 'currency': CurrencyCode('EUR')}}]
    monkeypatch.setattr(CanonicalInspector, 'documents', query)
    target = tmp_path / 'zero.csv'
    result = invoke(dataset, 'documents', '--company', 'Exact', '--year', '2024', '--month', '3',
                    '--csv', str(target))
    assert result.exit_code == 0, result.output
    row, = _read_document_csv(target)
    assert row['gross_amount'] == '0'
    assert row['gross_currency'] == 'EUR'
    assert row['net_amount'] == row['net_currency'] == ''


def test_documents_csv_missing_directory(dataset, tmp_path):
    target = tmp_path / 'missing' / 'export.csv'
    result = invoke(dataset, 'documents', '--csv', str(target))
    assert result.exit_code != 0
    assert 'Cannot write CSV' in result.output
    assert not target.parent.exists()


def test_documents_csv_query_failure_preserves_destination(tmp_path):
    target = tmp_path / 'export.csv'
    target.write_bytes(b'previous export')
    result = CliRunner().invoke(cli, ['--db', str(tmp_path / 'missing.sqlite'),
                                     'documents', '--csv', str(target)])
    assert result.exit_code != 0
    assert 'Error:' in result.output
    assert target.read_bytes() == b'previous export'
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize('dataset,expected_currency', [(CurrencyCode('EUR'), 'EUR'), (None, '')],
                         indirect=['dataset'])
def test_documents_csv_real_currency(dataset, tmp_path, expected_currency):
    from src.canonical_inspection import open_inspector
    with open_inspector(dataset[0]) as inspector:
        before = inspector.documents()
    for field in ('gross', 'net'):
        currency = before[0][field]['currency']
        assert currency == (CurrencyCode('EUR') if expected_currency else None)
        if expected_currency:
            assert isinstance(currency, CurrencyCode)
    target = tmp_path / 'currency.csv'
    database_bytes = dataset[0].read_bytes()
    result = invoke(dataset, 'documents', '--csv', str(target))
    assert result.exit_code == 0, result.output
    row, = _read_document_csv(target)
    assert row == dict(zip(CSV_COLUMNS, [dataset[1].document_id, '', '', '',
        'certified', '201.53', expected_currency, 'certified', '201.53', expected_currency], strict=True))
    assert 'CurrencyCode' not in target.read_text(encoding='utf-8-sig')
    with open_inspector(dataset[0]) as inspector:
        assert inspector.documents() == before
    assert dataset[0].read_bytes() == database_bytes
