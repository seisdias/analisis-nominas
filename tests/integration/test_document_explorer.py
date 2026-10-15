"""Exercise the actual Streamlit screen against synthetic canonical SQLite data."""

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.canonical.documents import (
    DocumentVersion,
    Extraction,
    LogicalDocument,
    document_id,
    extraction_id,
    version_id,
)
from src.canonical.economics import observation_id
from src.canonical.evidence import Corpus, Person, SourceFile, corpus_id, person_id, source_file_id
from src.canonical.facts import DocumentaryFact, FactDraft
from src.canonical.values import CanonicalValue, CurrencyCode, ExactDecimal, ValueState
from src.canonical_inspection import CanonicalInspector, InspectionError
from src.document_explorer import format_amount
from src.economic_mapping import evaluate_direct_totals
from src.persistence import open_database
from src.persistence.economics import EconomicRepository

APP = Path(__file__).resolve().parents[2] / 'app.py'


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr('src.cli_config.REPOSITORY_ROOT', tmp_path)
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.sqlite'
    with open_database(path, mode='create') as db:
        repo = EconomicRepository(db.connection)
        person = Person(person_id(), 'synthetic')
        corpus = Corpus(corpus_id(), person.person_id, 'synthetic', 'v1')
        source = SourceFile(source_file_id('a' * 64), 'a' * 64, 12, 'application/pdf')
        repo.register_person(person)
        repo.register_corpus(corpus)
        repo.register_source_file(source)
        for key, company, year, month in (
            ('certified', 'Empresa Alfa', 2024, 3),
            ('ambiguous', 'Empresa Beta', 2025, 4),
            ('absent', None, None, None),
            ('blocked', 'Empresa Beta', 2025, 5),
        ):
            doc = LogicalDocument(document_id(corpus.corpus_id, key), corpus.corpus_id,
                                  None, 'unknown', key)
            version = DocumentVersion(version_id(doc.document_id, source.file_id, 'whole'),
                                      doc.document_id, source.file_id, 'whole')
            ext = Extraction(extraction_id(version.version_id, 'synthetic', '1', 'b' * 64),
                             version.version_id, 'synthetic', '1', 'b' * 64, 'c' * 64)
            repo.register_document(doc)
            repo.register_version(version)
            repo.register_extraction(ext)
            for name, value in (('empresa', company), ('anio', year), ('mes', month)):
                if value is not None:
                    raw = ExactDecimal(value, 0) if isinstance(value, int) else value
                    repo.register_fact(DocumentaryFact.from_draft(ext.extraction_id,
                        FactDraft('nomina.' + name, CanonicalValue(state=ValueState.PRESENT,
                                                                  value=raw))))
            if key == 'absent':
                continue
            facts = tuple(DocumentaryFact.from_draft(ext.extraction_id, FactDraft(name,
                CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(123456, 2),
                               currency=CurrencyCode('EUR'))))
                for name in ('nomina.total_devengado', 'nomina.liquido_percibir'))
            for fact in facts:
                repo.register_fact(fact)
            result = evaluate_direct_totals(doc.document_id, facts)
            repo.register_rule(result.rule)
            repo.register_assessment(result.assessment)
            for item in result.observations:
                obs = item.observation
                if key == 'blocked':
                    obs = replace(obs, economic_status='pending')
                repo.register_observation(obs, item.fact_ids)
                if key == 'ambiguous':
                    other_key = 'extra-' + obs.observation_key
                    repo.register_observation(replace(obs, observation_key=other_key,
                        observation_id=observation_id(obs.assessment_id, other_key)), item.fact_ids)
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    return path


def screen():
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    return app


def test_companies_and_value_states_read_only(database):
    before = database.read_bytes()
    files = set(database.parent.iterdir())
    app = screen()
    assert app.title[0].value == 'Análisis de Nóminas'
    assert app.selectbox[0].options == ['Todas las empresas', 'Empresa Alfa', 'Empresa Beta']
    table = app.dataframe[0].value
    assert len(table) == 4
    assert set(table['Bruto']) == {'1.234,56 €', 'Sin observación',
                                  'Ambiguo', 'No certificado'}
    assert 'Empresa ausente o ambigua' in set(table['Empresa documental'])
    assert any('Bruto: Certificado · Neto: Certificado' == s
               for s in table['Certificación de valores'])
    assert database.read_bytes() == before
    assert set(database.parent.iterdir()) == files


def test_filters_and_empty_results(database, monkeypatch):
    original = CanonicalInspector.documents
    calls = []
    def query(self, **kwargs):
        calls.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(CanonicalInspector, 'documents', query)
    app = screen()
    app.selectbox[0].select('Empresa Beta')
    app.text_input[0].set_value('2025')
    app.selectbox[1].select(4)
    app.run()
    assert not app.exception
    assert calls[-1] == {'company': 'Empresa Beta', 'year': 2025, 'month': 4}
    table = app.dataframe[0].value
    assert list(table['Periodo documental']) == ['2025 / 04']
    assert list(table['Empresa documental']) == ['Empresa Beta']
    app.text_input[0].set_value('2024').run()
    assert not app.dataframe
    assert any('No hay documentos' in item.value for item in app.info)
    app.text_input[0].set_value('').run()
    assert len(app.dataframe[0].value) == 1


@pytest.mark.parametrize('year', ['0000', 'abcd', '-1', '２０２４'])
def test_invalid_year(database, year):
    app = screen()
    app.text_input[0].set_value(year).run()
    assert app.warning
    assert not app.dataframe
    assert not app.exception


@pytest.mark.parametrize('kind', ['missing', 'directory', 'invalid', 'empty'])
def test_unavailable_or_empty_database(tmp_path, monkeypatch, kind):
    path = tmp_path / 'database.sqlite'
    if kind == 'directory':
        path.mkdir()
    elif kind == 'invalid':
        path.write_bytes(b'not SQLite')
    elif kind == 'empty':
        with open_database(path, mode='create'):
            pass
    before = path.read_bytes() if path.is_file() else None
    monkeypatch.setenv('ANALISIS_NOMINAS_CANONICAL_DB', str(path))
    app = screen()
    assert not app.dataframe
    if kind == 'empty':
        assert 'No hay documentos' in app.info[0].value
    else:
        assert app.error
    assert path.exists() == (kind != 'missing')
    if before is not None:
        assert path.read_bytes() == before


def test_unconfigured_database(monkeypatch):
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB', raising=False)
    app = screen()
    assert 'no configurada' in app.warning[0].value


@pytest.mark.parametrize('method', ['companies', 'documents'])
def test_query_failure_removes_previous_results(database, monkeypatch, method):
    app = screen()
    assert app.dataframe
    def fail(*args, **kwargs):
        raise InspectionError('synthetic sensitive diagnostics')
    monkeypatch.setattr(CanonicalInspector, method, fail)
    app.run()
    assert not app.exception
    assert not app.dataframe
    assert 'No se pudo consultar' in app.error[0].value
    assert 'sensitive' not in app.error[0].value


@pytest.mark.parametrize('status', ['ambiguous', 'no_observation', 'not_certified'])
def test_uncertified_candidates_never_displayed(status):
    assert '999' not in format_amount({'status': status, 'amount': ExactDecimal(999, 0),
                                      'currency': CurrencyCode('EUR')})


@pytest.mark.parametrize('amount,currency,expected', [
    (ExactDecimal(0, 0), CurrencyCode('EUR'), '0,00 €'),
    (ExactDecimal(-123456, 2), CurrencyCode('USD'),
     'Inconsistencia de divisa: USD (ámbito EUR)'),
    (ExactDecimal(-123456, 2), None, '-1.234,56 €'),
    (ExactDecimal(1234567, 3), CurrencyCode('EUR'), '1.234,567 €'),
    (ExactDecimal(123456, 2), None, '1.234,56 €'),
    (ExactDecimal(123456, 2), CurrencyCode('EUR'), '1.234,56 €'),
    (None, None, 'Importe ausente'),
    (None, CurrencyCode('EUR'), 'Importe ausente'),
])
def test_exact_amount_presentation(amount, currency, expected):
    assert format_amount({'status': 'certified', 'amount': amount, 'currency': currency}) == expected


@pytest.mark.parametrize('currency', [None, CurrencyCode('EUR'), CurrencyCode('USD')])
def test_currency_scope_in_screen_preserves_evidence(database, monkeypatch, currency):
    original = CanonicalInspector.documents
    evidence = []
    def query(self, **kwargs):
        rows = original(self, **kwargs)
        for row in rows:
            for field in ('gross', 'net'):
                if row[field]['status'] == 'certified':
                    row[field]['currency'] = currency
                    evidence.append(row[field])
        return rows
    monkeypatch.setattr(CanonicalInspector, 'documents', query)
    before = database.read_bytes()
    app = screen()
    table = app.dataframe[0].value
    certified = table[table['Certificación de valores'] == 'Bruto: Certificado · Neto: Certificado']
    expected = ('Inconsistencia de divisa: USD (ámbito EUR)'
                if currency == CurrencyCode('USD') else '1.234,56 €')
    assert list(certified['Bruto']) == list(certified['Neto']) == [expected]
    assert 'Sin observación' in set(table['Bruto'])
    assert 'Ambiguo' in set(table['Bruto'])
    assert all(item['currency'] == currency and item['status'] == 'certified' for item in evidence)
    assert database.read_bytes() == before


def test_document_order_and_counts_do_not_merge_periods():
    from copy import deepcopy

    from src.document_explorer import document_counts, ordered_documents
    def row(identity, year, month, status='certified'):
        value = {'status': status, 'amount': ExactDecimal(100, 0), 'currency': None}
        return {'document_id': identity, 'year': year, 'month': month,
                'company_text': 'Same company', 'gross': value.copy(), 'net': value.copy()}
    rows = [row('b', 2025, 4), row('old', 2024, 12), row('a', 2025, 4),
            row('new', 2025, 5), row('unknown', None, None), row('partial', 2026, None)]
    before = deepcopy(rows)
    assert [r['document_id'] for r in ordered_documents(rows)] == [
        'new', 'a', 'b', 'old', 'partial', 'unknown']
    assert ordered_documents(list(reversed(rows))) == ordered_documents(rows)
    assert document_counts(rows + [deepcopy(rows[0])]) == (6, 6)
    assert rows == before
    for status in ('ambiguous', 'no_observation', 'not_certified'):
        mixed = row('mixed', 2025, 4)
        mixed['net']['status'] = status
        assert document_counts([rows[0], mixed, deepcopy(mixed)]) == (2, 1)
    conflict = deepcopy(rows[0])
    conflict['net']['amount'] = ExactDecimal(101, 0)
    assert document_counts([rows[0], conflict]) == (1, 0)


def test_summary_table_and_selection_follow_filters(database):
    import json
    app = screen()
    assert [item.value for item in app.metric] == ['4', '1']
    assert not app.button
    table = app.dataframe[0]
    assert list(table.proto.column_order) == ['Periodo documental', 'Empresa documental', 'Bruto', 'Neto']
    config = json.loads(table.proto.columns)
    assert config['Bruto']['alignment'] == config['Neto']['alignment'] == 'right'
    assert list(table.value['Periodo documental'])[:3] == ['2025 / 05', '2025 / 04', '2024 / 03']
    identity = table.value.iloc[0]['Identificador']
    app.session_state[table.key] = {'selection': {'rows': [0], 'columns': [], 'cells': []}}
    app.run()
    assert not app.exception
    assert app.code[0].value == identity
    app.selectbox[0].select('Empresa Alfa').run()
    assert [item.value for item in app.metric] == ['1', '1']
    assert not app.code  # Stale selection cannot identify a different document.
    app.text_input[0].set_value('2000').run()
    assert [item.value for item in app.metric] == ['0', '0']
    assert not app.dataframe


def test_different_documents_same_period_remain_visible(database, monkeypatch):
    from copy import deepcopy
    original = CanonicalInspector.documents
    def query(self, **kwargs):
        rows = original(self, **kwargs)
        other = deepcopy(rows[0])
        other['document_id'] += '-distinct'
        return [*rows, other]
    monkeypatch.setattr(CanonicalInspector, 'documents', query)
    app = screen()
    table = app.dataframe[0].value
    assert len(table) == 5
    assert table['Identificador'].nunique() == 5
    assert app.metric[0].value == '5'


def test_gui_uses_shared_toml_and_read_only_connection(database, monkeypatch, tmp_path):
    import sqlite3

    from click.testing import CliRunner

    from src.cli import cli
    from src.cli_config import load_config
    monkeypatch.delenv('ANALISIS_NOMINAS_CANONICAL_DB')
    (tmp_path / 'config.toml').write_text(
        '[paths]\ndatabase="synthetic.sqlite"\npayroll_directory="documents"\n')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    before = database.read_bytes()
    files = set(tmp_path.iterdir())
    original = CanonicalInspector.companies
    def checked(self):
        assert self._connection.execute('PRAGMA query_only').fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            self._connection.execute('CREATE TABLE forbidden_write (id INTEGER)')
        return original(self)
    monkeypatch.setattr(CanonicalInspector, 'companies', checked)
    app = screen()
    assert app.dataframe
    assert any('SQLite accesible' in item.value for item in app.success)
    diagnostic = next(e for e in app.expander if e.label == 'Configuración y diagnóstico')
    texts = '\n'.join(item.value for item in diagnostic.text)
    assert str(load_config().database) in texts
    assert 'config.toml' in texts
    assert str(tmp_path / 'documents') in texts
    cli_result = CliRunner().invoke(cli, ['config'])
    assert cli_result.exit_code == 0
    assert str(load_config().database) in cli_result.output
    assert database.read_bytes() == before
    assert set(tmp_path.iterdir()) == files


def test_gui_environment_overrides_toml(database, tmp_path):
    (tmp_path / 'config.toml').write_text('[paths]\ndatabase="missing.sqlite"\n')
    app = screen()
    assert app.dataframe
    assert any('ANALISIS_NOMINAS_CANONICAL_DB' in item.value for item in app.text)


def test_gui_invalid_toml(tmp_path):
    (tmp_path / 'config.toml').write_text('[invalid SENSITIVE_CONFIG')
    app = screen()
    assert not app.dataframe
    assert 'config.toml' in app.warning[0].value
    assert 'SENSITIVE_CONFIG' not in app.warning[0].value


def test_gui_inaccessible_database(database, monkeypatch, caplog):
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == database:
            raise PermissionError('SENSITIVE_PATH')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    app = screen()
    assert not app.dataframe
    assert 'No se pudo consultar' in app.error[0].value
    assert 'SENSITIVE_PATH' not in app.error[0].value
    assert 'SENSITIVE_PATH' not in caplog.text
