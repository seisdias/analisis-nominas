"""Builder CLI on generated PDFs, production extraction/parser/ingestion only."""
import json
from uuid import UUID

import pytest
from click.testing import CliRunner

from src.canonical_builder import cli
from src.persistence import open_database
from src.persistence.state import CanonicalStateReader


def synthetic_pdf() -> bytes:
    # Synthetic Coritel-format text, not a private PDF or a parser mock.
    lines = ['EMPRESA: Coritel, S.A. GRUPO COTIZACIÓN: 03', 'CIF: A00000000',
             'PERIODO DE LIQUIDACIÓN: 01.04.2099 - 30.04.2099 Total días: 30',
             'Salario base 900,00', 'TOTAL DEVENGADO 900,00',
             'TOTAL A DEDUCIR 100,00', 'LIQUIDO TOTAL A PERCIBIR (A-B) 800,00']
    stream = b'BT /F1 10 Tf 40 780 Td 16 TL\n' + b'\n'.join(
        b'(' + line.encode('cp1252').replace(b'(', b'\\(').replace(b')', b'\\)') + b') Tj T*'
        for line in lines) + b'\nET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    data = b'%PDF-1.4\n'
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n'
    start = len(data)
    data += b'xref\n0 6\n0000000000 65535 f \n'
    data += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    return data + f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()


@pytest.fixture
def config(tmp_path):
    source = tmp_path / 'sources'
    source.mkdir()
    (source / 'synthetic.pdf').write_bytes(synthetic_pdf())
    data = {'version': 1, 'application_revision': 'synthetic-build/v1',
            'person': {'seed': str(UUID(int=1)), 'alias': 'synthetic'},
            'corpora': [{'seed': str(UUID(int=2)), 'name': 'unrelated-corpus-label',
                         'source': 'sources', 'manifest_contract': 'synthetic/v1',
                         'processor': {'kind': 'ordinary', 'parser': 'coritel'}, 'exclusions': []}]}
    path = tmp_path / 'build.json'
    path.write_text(json.dumps(data))
    return path, data


def run(config, output):
    return CliRunner().invoke(cli, ['--config', str(config), '--output', str(output)])


def test_help():
    result = CliRunner().invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert '--output' in result.output and '--config' in result.output


def test_real_synthetic_pipeline_and_schema(config, tmp_path):
    path, _ = config
    output = tmp_path / 'out.sqlite'
    result = run(path, output)
    assert result.exit_code == 0, result.output
    assert 'inventoried: 1' in result.output
    assert 'processed: 1' in result.output
    assert 'failed: 0' in result.output
    assert 'schema version: 8' in result.output
    with open_database(output, mode='verify') as db:
        assert db.status.current_version == 8
        assert db.connection.execute('SELECT count(*) FROM documentary_facts').fetchone()[0] > 0
        assert db.connection.execute('SELECT count(*) FROM economic_observations').fetchone()[0] == 2
        assert db.connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_equivalent_builds_ignore_enumeration_output_path_and_cwd(config, tmp_path, monkeypatch):
    path, data = config
    other = dict(data['corpora'][0], seed=str(UUID(int=3)), name='second-arbitrary-name')
    data['corpora'].append(other)
    path.write_text(json.dumps(data))
    a, b = tmp_path/'a.sqlite', tmp_path/'b.sqlite'
    assert run(path, a).exit_code == 0
    data['corpora'].reverse()
    path.write_text(json.dumps(data))
    monkeypatch.chdir(tmp_path.parent)
    assert run(path, b).exit_code == 0
    with open_database(a) as db_a, open_database(b) as db_b:
        assert CanonicalStateReader(db_a.connection).read() == CanonicalStateReader(db_b.connection).read()


@pytest.mark.parametrize('symlink', [False, True])
def test_existing_destination_is_never_overwritten(config, tmp_path, symlink):
    output = tmp_path/'existing.sqlite'
    if symlink:
        output.symlink_to(tmp_path/'missing.sqlite')
    else:
        output.write_bytes(b'keep me')
    result = run(config[0], output)
    assert result.exit_code != 0
    assert 'exists' in result.output
    assert output.is_symlink() if symlink else output.read_bytes() == b'keep me'


def test_explicit_exclusion_is_skip_reason(config, tmp_path):
    path, data = config
    data['corpora'][0]['exclusions'] = [{'path': 'synthetic.pdf', 'reason_code': 'declared_omission'}]
    path.write_text(json.dumps(data))
    output = tmp_path/'skip.sqlite'
    result = run(path, output)
    assert result.exit_code == 0, result.output
    assert 'skipped: 1' in result.output
    with open_database(output) as db:
        assert db.connection.execute('SELECT status,reason_code FROM ingest_items').fetchall() == [('skipped', 'declared_omission')]
        assert db.connection.execute('SELECT count(*) FROM logical_documents').fetchone()[0] == 0


@pytest.mark.parametrize('case', ['bad_version', 'duplicate_corpus', 'bad_parser', 'bad_reason',
                                  'missing_exclusion', 'unknown_key', 'random_seed'])
def test_invalid_configuration(config, tmp_path, case):
    path, data = config
    corpus = data['corpora'][0]
    if case == 'bad_version':
        data['version'] = True
    elif case == 'duplicate_corpus':
        data['corpora'].append(corpus)
    elif case == 'bad_parser':
        corpus['processor']['parser'] = 'not-a-parser'
    elif case == 'bad_reason':
        corpus['exclusions'] = [{'path': 'synthetic.pdf', 'reason_code': 'invalid reason'}]
    elif case == 'missing_exclusion':
        corpus['exclusions'] = [{'path': 'absent.pdf', 'reason_code': 'declared'}]
    elif case == 'random_seed':
        corpus.pop('seed')
    else:
        corpus['exlcusions'] = []
    path.write_text(json.dumps(data))
    output = tmp_path/'bad.sqlite'
    result = run(path, output)
    assert result.exit_code != 0
    assert 'Error:' in result.output
    assert not output.exists()


def test_failure_does_not_publish_partial_database(config, tmp_path):
    path, _ = config
    (tmp_path/'sources'/'broken.pdf').write_bytes(b'not a PDF')
    result = run(path, tmp_path/'failed.sqlite')
    assert result.exit_code != 0
    assert 'failed: 1' in result.output
    assert not (tmp_path/'failed.sqlite').exists()
    assert not list(tmp_path.glob('.canonical-build-*'))


def test_destination_created_during_build_is_not_overwritten(config, tmp_path, monkeypatch):
    import src.canonical_build as module
    original = module.ingest
    output = tmp_path/'race.sqlite'
    def concurrent_destination(*args, **kwargs):
        result = original(*args, **kwargs)
        output.write_bytes(b'concurrent owner')
        return result
    monkeypatch.setattr(module, 'ingest', concurrent_destination)
    result = run(config[0], output)
    assert result.exit_code != 0
    assert output.read_bytes() == b'concurrent owner'


def test_duplicate_json_keys_rejected(config, tmp_path):
    config[0].write_text('{"version":1,"version":1}')
    assert run(config[0], tmp_path/'bad.sqlite').exit_code != 0


def test_empty_corpus_rejected(config, tmp_path):
    (tmp_path/'sources'/'synthetic.pdf').unlink()
    result = run(config[0], tmp_path/'empty.sqlite')
    assert result.exit_code != 0
    assert 'at least one PDF' in result.output
    assert not (tmp_path/'empty.sqlite').exists()


def test_parent_not_created_implicitly(config, tmp_path):
    result = run(config[0], tmp_path/'absent'/'out.sqlite')
    assert result.exit_code != 0
    assert not (tmp_path/'absent').exists()


def test_insis_alias_is_configuration_and_alten_uses_existing_processor(config, tmp_path, monkeypatch):
    import src.canonical_build as module
    path, data = config
    calls = []
    factory_method = module.ParserFactory.obtener_parser
    def capture(factory, selector):
        calls.append(selector)
        return factory_method(factory, selector)
    monkeypatch.setattr(module.ParserFactory, 'obtener_parser', capture)
    for kind, parser in [('ordinary', 'insis'), ('alten', None)]:
        corpus = data['corpora'][0]
        corpus['name'] = 'arbitrary-name'
        corpus['processor'] = {'kind': kind, **({'parser': parser} if parser else {})}
        corpus['exclusions'] = [{'path': 'synthetic.pdf', 'reason_code': 'explicit_skip'}]
        path.write_text(json.dumps(data))
        result = run(path, tmp_path/f'{kind}.sqlite')
        assert result.exit_code == 0, result.output
    assert calls == ['insis']


def test_builder_result_can_be_read_by_inspector(config, tmp_path):
    from src.canonical_inspector import cli as inspect_cli
    output = tmp_path/'inspectable.sqlite'
    assert run(config[0], output).exit_code == 0
    before = output.read_bytes()
    result = CliRunner().invoke(inspect_cli, ['--db', str(output), 'summary'])
    assert result.exit_code == 0, result.output
    assert 'logical_documents: 1' in result.output
    assert output.read_bytes() == before
