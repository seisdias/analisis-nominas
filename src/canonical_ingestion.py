"""Serial, explicit-plan orchestration; company/parser logic lives in processors."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from src.canonical.evidence import (
    FileLocation,
    IngestItem,
    IngestRun,
    SourceFile,
    _id,
    _path,
    _sha,
    _text,
    source_file_id,
    utc_now,
)
from src.canonical.identifiers import ReproducibilityConflict
from src.canonical.serialization import canonical_sha256, sha256_bytes
from src.persistence.relations import RelationRepository


@dataclass(frozen=True)
class CorpusInput:
    corpus_id: str
    root: Path
    processor_id: str

    def __post_init__(self) -> None:
        _id(self.corpus_id, 'corpus')
        _text(self.processor_id)


@dataclass(frozen=True)
class InputPDF:
    corpus_id: str
    relative_path: str
    sha256: str
    processor_id: str
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        _id(self.corpus_id, 'corpus')
        _path(self.relative_path)
        _sha(self.sha256)
        _text(self.processor_id)
        if self.skip_reason is not None:
            # Reuse inventory's reason-code contract before making any writes.
            IngestItem('ingest_run:sha256:'+'0'*64, 'validation', self.corpus_id,
                       self.relative_path, status='skipped', reason_code=self.skip_reason)


class PreparedPDF(Protocol):
    page_count: int | None
    skip_reason: str | None

    def persist(self, repo: RelationRepository, file: SourceFile,
                location: FileLocation, stamp: str) -> None: ...


class PDFProcessor(Protocol):
    revision: str

    def prepare(self, data: bytes, filename: str) -> PreparedPDF: ...


def _path_for(binding: CorpusInput, relative: str) -> Path:
    _path(relative)
    root = binding.root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Source escapes explicit corpus root')
    return path


def inventory(corpora: Sequence[CorpusInput]) -> tuple[InputPDF, ...]:
    """Hash explicit roots; persist only normalized relative paths, never roots."""
    result = []
    for binding in corpora:
        if not binding.root.is_dir():
            raise ValueError('Missing corpus directory')
        for path in sorted(binding.root.rglob('*')):
            if path.is_file() and path.suffix.lower() == '.pdf':
                relative = path.relative_to(binding.root).as_posix()
                data = _path_for(binding, relative).read_bytes()
                result.append(InputPDF(binding.corpus_id, relative, sha256_bytes(data), binding.processor_id))
    return tuple(sorted(result, key=_order))


def _order(item: InputPDF) -> tuple[str, str, str]:
    return item.corpus_id, item.sha256, item.relative_path


@dataclass(frozen=True)
class IngestionSummary:
    run_id: str
    processed: int
    skipped: int
    failed: int


def ingest(repo: RelationRepository, corpora: Sequence[CorpusInput],
           processors: Mapping[str, PDFProcessor], *, sources: Sequence[InputPDF] | None = None) -> IngestionSummary:
    """Every PDF commits together with its terminal item; failure commits only item.

    Replays skip all terminal items (including failures); explicit new plans are
    required for retries. No implicit attempts, parser calls or timestamp changes.
    Root relocation does not change plan identity. Inputs are rehashed before use.
    """
    bindings = {b.corpus_id: b for b in corpora}
    if len(bindings) != len(corpora):
        raise ValueError('Duplicate corpus binding')
    ordered = tuple(sorted(inventory(corpora) if sources is None else sources, key=_order))
    if len({(s.corpus_id, s.relative_path) for s in ordered}) != len(ordered):
        raise ValueError('Repeated path in plan')
    for binding in corpora:
        if repo.get_corpus(binding.corpus_id) is None or binding.processor_id not in processors:
            raise ValueError('Explicit registered corpus and processor required')
    for planned_source in ordered:
        if planned_source.corpus_id not in bindings or bindings[planned_source.corpus_id].processor_id != planned_source.processor_id:
            raise ValueError('Input does not match corpus processor')
    plan = {'contract': 'canonical-ingestion/v1',
            'processors': {key: processors[key].revision for key in sorted({b.processor_id for b in corpora})},
            'sources': [{**asdict(s), 'corpus_id': str(s.corpus_id)} for s in ordered]}
    run = IngestRun.from_plan(plan)
    items = tuple(IngestItem(run.run_id, canonical_sha256({'corpus': str(s.corpus_id), 'path': s.relative_path}),
                            s.corpus_id, s.relative_path, s.sha256) for s in ordered)
    with repo.transaction():
        repo.create_run(run)
        for item in items:
            if repo.get_item(item.run_id, item.item_key) is None:
                repo.register_item(item)
    for source, item in zip(ordered, items, strict=True):
        existing = repo.get_item(item.run_id, item.item_key)
        assert existing is not None
        if existing.status != 'pending':
            if existing.status in ('processed', 'skipped'):
                try:
                    actual = sha256_bytes(_path_for(bindings[source.corpus_id], source.relative_path).read_bytes())
                except OSError as error:
                    raise ReproducibilityConflict('Completed source is no longer available') from error
                if actual != source.sha256:
                    raise ReproducibilityConflict('Completed source differs from planned bytes')
            continue
        try:
            data = _path_for(bindings[source.corpus_id], source.relative_path).read_bytes()
            if sha256_bytes(data) != source.sha256:
                raise ReproducibilityConflict('Source differs from planned bytes')
            prepared = None if source.skip_reason else processors[source.processor_id].prepare(data, Path(source.relative_path).name)
            reason = source.skip_reason if prepared is None else prepared.skip_reason
            stamp = utc_now()
            file = SourceFile(source_file_id(source.sha256), source.sha256, len(data), 'application/pdf',
                              page_count=None if prepared is None else prepared.page_count, created_at=stamp)
            location = FileLocation(source.corpus_id, source.relative_path, file.file_id,
                                    Path(source.relative_path).name, stamp)
            with repo.transaction():
                repo.register_source_file(file)
                repo.register_location(location)
                if prepared is not None and reason is None:
                    prepared.persist(repo, file, location, stamp)
                repo.update_item(replace(item, file_id=file.file_id,
                                         status='skipped' if reason else 'processed', reason_code=reason))
        except Exception as error:
            # Never persist exception messages, tracebacks, paths or personal data.
            reason = 'reproducibility_conflict' if isinstance(error, ReproducibilityConflict) else 'processing_failed'
            repo.update_item(replace(item, status='failed', reason_code=reason, error_detail='omitted'))
    final = [repo.get_item(item.run_id, item.item_key) for item in items]
    statuses = [item.status for item in final if item is not None]
    repo.finish_run(run.run_id, 'partial' if 'failed' in statuses else 'complete', utc_now())
    return IngestionSummary(run.run_id, statuses.count('processed'), statuses.count('skipped'), statuses.count('failed'))
