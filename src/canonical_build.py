"""Declarative construction using T6 ingestion; no economic or parser policy."""
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from src.canonical.evidence import Corpus, Person, corpus_id, person_id
from src.canonical_ingestion import (
    CorpusInput,
    IngestionSummary,
    InputPDF,
    PDFProcessor,
    ingest,
    inventory,
)
from src.ingestion_processors import AltenProcessor, OrdinaryProcessor
from src.parsers.parser_factory import ParserFactory
from src.persistence import open_database, verify_schema
from src.persistence.relations import RelationRepository


@dataclass(frozen=True)
class CorpusBuild:
    corpus: Corpus
    source: Path
    processor_kind: str
    parser: str | None
    exclusions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BuildConfig:
    person: Person
    corpora: tuple[CorpusBuild, ...]
    application_revision: str


@dataclass(frozen=True)
class BuildReport:
    inventoried: int
    ingestion: IngestionSummary
    schema_version: int


class BuildError(ValueError):
    def __init__(self, message: str, report: BuildReport | None = None) -> None:
        super().__init__(message)
        self.report = report


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BuildError(f'Duplicate configuration key: {key}')
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise BuildError('Configuration does not accept floats or nonfinite numbers')


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - (optional or set()):
        raise BuildError(f'Expected configuration fields: {", ".join(sorted(required))}')
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise BuildError('Expected nonempty configuration text')
    return value


def load_config(path: Path) -> BuildConfig:
    """Relative sources resolve against JSON location, not cwd. Seeds are explicit UUIDs."""
    raw = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_object,
                     parse_float=_reject_number, parse_constant=_reject_number)
    raw = _keys(raw, {'version', 'application_revision', 'person', 'corpora'})
    if type(raw['version']) is not int or raw['version'] != 1:
        raise BuildError('Unsupported build configuration version; expected 1')
    p = _keys(raw['person'], {'seed', 'alias'})
    person = Person(person_id(UUID(_text(p['seed']))), _text(p['alias']))
    if not isinstance(raw['corpora'], list) or not raw['corpora']:
        raise BuildError('At least one corpus is required')
    corpora = []
    for item in raw['corpora']:
        item = _keys(item, {'seed', 'name', 'source', 'manifest_contract', 'processor'}, {'exclusions'})
        corpus = Corpus(corpus_id(UUID(_text(item['seed']))), person.person_id,
                        _text(item['name']), _text(item['manifest_contract']))
        processor = _keys(item['processor'], {'kind'}, {'parser'})
        kind = processor['kind']
        if kind == 'ordinary':
            parser = _text(processor.get('parser'))
        elif kind == 'alten' and 'parser' not in processor:
            parser = None
        else:
            raise BuildError('Processor must be ordinary with parser, or alten without parser')
        excluded = item.get('exclusions', [])
        if not isinstance(excluded, list):
            raise BuildError('Exclusions must be a list')
        exclusions = []
        for entry in excluded:
            entry = _keys(entry, {'path', 'reason_code'})
            relative, reason = _text(entry['path']), _text(entry['reason_code'])
            # Validate through the existing path/reason contract, not a new vocabulary.
            InputPDF(corpus.corpus_id, relative, '0'*64, corpus.label, reason)
            exclusions.append((relative, reason))
        if len({p for p, _ in exclusions}) != len(exclusions):
            raise BuildError('Duplicate exclusion path')
        source = (path.resolve().parent / _text(item['source'])).resolve()
        corpora.append(CorpusBuild(corpus, source, kind, parser, tuple(sorted(exclusions))))
    if (len({c.corpus.corpus_id for c in corpora}) != len(corpora)
            or len({c.corpus.label for c in corpora}) != len(corpora)):
        raise BuildError('Corpus seeds and names must be unique')
    return BuildConfig(person, tuple(sorted(corpora, key=lambda c: c.corpus.corpus_id)),
                       _text(raw['application_revision']))


def build(config: BuildConfig, output: Path) -> BuildReport:
    """Publish only a complete, verified build, with atomic no-clobber hard linking.

    Staging is private and on the destination filesystem. Failures clean only our
    staging directory, never an existing destination or source. No force mode.
    Parent directory must already exist. Hard-link support is required; no unsafe
    overwrite/copy fallback. The closed published SQLite is owner-readable only.
    """
    if os.path.lexists(output):
        raise BuildError('Output already exists; choose a new path')
    if not output.parent.is_dir() or not output.name:
        raise BuildError('Output parent must be an existing directory')
    factory = ParserFactory()
    processors: dict[str, PDFProcessor] = {}
    bindings = []
    for spec in config.corpora:
        processors[spec.corpus.label] = (AltenProcessor() if spec.processor_kind == 'alten'
            else OrdinaryProcessor(factory.obtener_parser(_text(spec.parser))))
        bindings.append(CorpusInput(spec.corpus.corpus_id, spec.source, spec.corpus.label))
    sources = inventory(bindings)
    exclusions = {(spec.corpus.corpus_id, path): reason
                  for spec in config.corpora for path, reason in spec.exclusions}
    found = {(s.corpus_id, s.relative_path) for s in sources}
    if exclusions.keys() - found:
        raise BuildError('Declared exclusion not found in inventory; no build published')
    if {s.corpus_id for s in sources} != {b.corpus_id for b in bindings}:
        raise BuildError('Each configured corpus must contain at least one PDF')
    sources = tuple(replace(s, skip_reason=exclusions.get((s.corpus_id, s.relative_path))) for s in sources)
    with TemporaryDirectory(prefix='.canonical-build-', dir=output.parent) as directory:
        staged = Path(directory) / 'candidate.sqlite'
        with open_database(staged, mode='create', application_revision=config.application_revision) as db:
            repo = RelationRepository(db.connection)
            repo.register_person(config.person)
            for spec in config.corpora:
                repo.register_corpus(spec.corpus)
            result = ingest(repo, bindings, processors, sources=sources)
            status = verify_schema(db.connection)
            report = BuildReport(len(sources), result, status.current_version)
            if result.failed:
                raise BuildError('Ingestion failed; no database published', report)
            if status.current_version != 8 or status.pending_versions:
                raise BuildError('Expected complete schema v8; no database published', report)
        os.chmod(staged, 0o600)
        with staged.open('rb') as handle:
            os.fsync(handle.fileno())
        # Unlike rename/replace, link refuses even a concurrently created destination.
        os.link(staged, output)
    return report
