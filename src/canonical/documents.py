"""Document provenance contracts without extraction payloads or economic meaning."""

from dataclasses import dataclass, field

from src.canonical.evidence import _id, _sha, _text, _time, utc_now
from src.canonical.identifiers import CanonicalId
from src.canonical.serialization import deterministic_id


def document_id(corpus_id: str, origin_key: str) -> CanonicalId:
    _id(corpus_id, 'corpus')
    _text(origin_key)
    return deterministic_id('document', {'corpus_id': str(corpus_id), 'origin_key': origin_key})


def version_id(document_id: str, file_id: str, segment_key: str) -> CanonicalId:
    _id(document_id, 'document')
    _id(file_id, 'file')
    _text(segment_key)
    return deterministic_id('version', {'document_id': str(document_id), 'file_id': str(file_id),
                                        'segment_key': segment_key})


def extraction_id(version_id: str, extractor_name: str, extractor_revision: str,
                  config_hash: str) -> CanonicalId:
    _id(version_id, 'version')
    _text(extractor_name)
    _text(extractor_revision)
    _sha(config_hash)
    return deterministic_id('extraction', {
        'version_id': str(version_id), 'extractor_name': extractor_name,
        'extractor_revision': extractor_revision, 'config_hash': config_hash,
    })


@dataclass(frozen=True, slots=True)
class LogicalDocument:
    document_id: str
    corpus_id: str
    employer_id: str | None
    document_type: str
    origin_key: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.document_id != document_id(self.corpus_id, self.origin_key):
            raise ValueError('Document identity does not match corpus and origin key')
        if self.employer_id is not None:
            _id(self.employer_id, 'employer')
        _text(self.document_type)
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    version_id: str
    document_id: str
    file_id: str
    segment_key: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.version_id != version_id(self.document_id, self.file_id, self.segment_key):
            raise ValueError('Version identity does not match document, file and segment')
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class VersionPage:
    version_id: str
    page_number: int
    ordinal: int

    def __post_init__(self) -> None:
        _id(self.version_id, 'version')
        if type(self.page_number) is not int or not 0 < self.page_number < 2**63:
            raise ValueError('Positive SQLite-compatible integer page number required')
        if type(self.ordinal) is not int or not 0 <= self.ordinal < 2**63:
            raise ValueError('Nonnegative SQLite-compatible integer ordinal required')


@dataclass(frozen=True, slots=True)
class Extraction:
    extraction_id: str
    version_id: str
    extractor_name: str
    extractor_revision: str
    config_hash: str
    content_hash: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        expected = extraction_id(self.version_id, self.extractor_name,
                                 self.extractor_revision, self.config_hash)
        if self.extraction_id != expected:
            raise ValueError('Extraction identity does not match its reproducibility inputs')
        _sha(self.content_hash)
        _time(self.created_at)
