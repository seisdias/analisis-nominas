"""Physical evidence contracts: no SQL, parser or payroll model dependencies."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.canonical.identifiers import CanonicalId, ReproducibilityConflict
from src.canonical.serialization import canonical_bytes, deterministic_id, sha256_bytes


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError('Nonempty text required')


def _sha(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Lowercase SHA256 required')


def _id(value: str, namespace: str) -> None:
    if CanonicalId(value).namespace != namespace:
        raise ValueError('Wrong identity namespace')


def _time(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError('UTC ISO 8601 timestamp required')


def _path(value: str) -> None:
    _text(value)
    if '\\' in value or ':' in value or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Normalized relative POSIX path required')


def _seed(namespace: str, seed: UUID | None) -> CanonicalId:
    if seed is not None and not isinstance(seed, UUID):
        raise TypeError('Explicit seed must be UUID')
    return deterministic_id(namespace, {'uuid': str(seed if seed is not None else uuid4())})


def person_id(seed: UUID | None = None) -> CanonicalId:
    return _seed('person', seed)


def corpus_id(seed: UUID | None = None) -> CanonicalId:
    return _seed('corpus', seed)


def employer_id(country: str, tax_id: str | None = None, *, seed: UUID | None = None) -> CanonicalId:
    if not re.fullmatch('[A-Z]{2}', country):
        raise ValueError('Uppercase two-letter country required')
    if tax_id is None:
        return _seed('employer', seed)
    _text(tax_id)
    if tax_id != tax_id.strip() or seed is not None:
        raise ValueError('Tax identifier must be explicit and unpadded; do not also supply a seed')
    return deterministic_id('employer', {'country': country, 'tax_id': tax_id})


def source_file_id(sha256: str) -> CanonicalId:
    _sha(sha256)
    return deterministic_id('file', {'sha256': sha256})


def ingest_run_id(plan_hash: str) -> CanonicalId:
    _sha(plan_hash)
    return deterministic_id('ingest_run', {'plan_hash': plan_hash, 'contract_version': 1})


@dataclass(frozen=True, slots=True)
class Person:
    person_id: str
    local_alias: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _id(self.person_id, 'person')
        _text(self.local_alias)
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class Employer:
    employer_id: str
    country: str
    tax_id: str | None
    display_name: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _id(self.employer_id, 'employer')
        if not re.fullmatch('[A-Z]{2}', self.country):
            raise ValueError('Uppercase two-letter country required')
        if self.tax_id is not None and self.employer_id != employer_id(self.country, self.tax_id):
            raise ValueError('Employer identity does not match tax identity')
        _text(self.display_name)
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class Corpus:
    corpus_id: str
    person_id: str
    label: str
    manifest_contract: str
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _id(self.corpus_id, 'corpus')
        _id(self.person_id, 'person')
        _text(self.label)
        _text(self.manifest_contract)
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class SourceFile:
    file_id: str
    sha256: str
    byte_size: int
    media_type: str
    page_count: int | None = None
    availability: str = 'available'
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.file_id != source_file_id(self.sha256):
            raise ValueError('File identity does not match SHA256')
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError('Nonnegative integer byte size required')
        if self.page_count is not None and (type(self.page_count) is not int or self.page_count <= 0):
            raise ValueError('Positive integer page count required')
        _text(self.media_type)
        if self.availability not in ('available', 'not_located', 'withdrawn'):
            raise ValueError('Invalid availability')
        _time(self.created_at)


@dataclass(frozen=True, slots=True)
class FileLocation:
    corpus_id: str
    relative_path: str
    file_id: str
    original_filename: str
    first_seen_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _id(self.corpus_id, 'corpus')
        _id(self.file_id, 'file')
        _path(self.relative_path)
        _path(self.original_filename)
        if '/' in self.original_filename:
            raise ValueError('Filename must be a basename')
        _time(self.first_seen_at)


def _decode_plan(node: object) -> object:
    """Plans deliberately support JSON data only, using canonical tagged bytes.

    Decode then re-encode to reject alternate integer spellings, unordered/duplicate
    maps and malformed type tags without duplicating the identity encoder.
    """
    if not isinstance(node, list) or not node:
        raise ValueError('Invalid plan node')
    if node == ['null']:
        return None
    if len(node) != 2:
        raise ValueError('Invalid plan node shape')
    tag, value = node
    if tag == 'str' and type(value) is str:
        return value
    if tag == 'bool' and type(value) is bool:
        return value
    if tag == 'int' and type(value) is str:
        return int(value)
    if tag == 'list' and isinstance(value, list):
        return [_decode_plan(item) for item in value]
    if tag == 'map' and isinstance(value, list):
        result: dict[str, object] = {}
        for entry in value:
            if not isinstance(entry, list) or len(entry) != 2 or type(entry[0]) is not str:
                raise ValueError('Invalid plan map entry')
            if entry[0] in result:
                raise ValueError('Duplicate plan map key')
            result[entry[0]] = _decode_plan(entry[1])
        return result
    raise ValueError('Plan supports only null, bool, int, text, list and map')


@dataclass(frozen=True, slots=True)
class IngestRun:
    run_id: str
    plan_hash: str
    contract_version: int
    plan_json: str
    status: str = 'running'
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    @classmethod
    def from_plan(cls, plan: object, *, started_at: str | None = None) -> 'IngestRun':
        payload = canonical_bytes(plan)
        digest = sha256_bytes(payload)
        return cls(ingest_run_id(digest), digest, 1, payload.decode('utf-8'),
                   started_at=started_at if started_at is not None else utc_now())

    def __post_init__(self) -> None:
        _sha(self.plan_hash)
        if type(self.contract_version) is not int or self.contract_version != 1:
            raise ValueError('Unsupported ingestion plan contract')
        if self.run_id != ingest_run_id(self.plan_hash):
            raise ReproducibilityConflict('Run identity does not match plan hash')
        if sha256_bytes(self.plan_json.encode('utf-8')) != self.plan_hash:
            raise ReproducibilityConflict('Plan hash does not match content')
        def reject_float(value: str) -> None:
            raise ValueError('Plan contains a noncanonical number')
        payload = json.loads(self.plan_json, parse_float=reject_float, parse_constant=reject_float)
        # Plans use the existing typed canonical envelope, not ordinary ad-hoc JSON.
        if (not isinstance(payload, dict) or set(payload) != {'contract', 'version', 'value'}
                or payload['contract'] != 'canonical' or type(payload['version']) is not int
                or payload['version'] != 1):
            raise ValueError('Canonical serialization envelope required')
        if json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')) != self.plan_json:
            raise ValueError('Noncanonical plan encoding')
        if canonical_bytes(_decode_plan(payload['value'])).decode('utf-8') != self.plan_json:
            raise ValueError('Noncanonical plan content')
        if self.status not in ('running', 'complete', 'partial'):
            raise ValueError('Invalid run status')
        _time(self.started_at)
        if (self.status == 'running') != (self.finished_at is None):
            raise ValueError('Finished timestamp must agree with run status')
        if self.finished_at is not None:
            _time(self.finished_at)
            if datetime.fromisoformat(self.finished_at) < datetime.fromisoformat(self.started_at):
                raise ValueError('Run ends before it starts')


@dataclass(frozen=True, slots=True)
class IngestItem:
    run_id: str
    item_key: str
    corpus_id: str
    relative_path: str
    expected_sha256: str | None = None
    file_id: str | None = None
    status: str = 'pending'
    reason_code: str | None = None
    error_detail: str | None = None

    def __post_init__(self) -> None:
        _id(self.run_id, 'ingest_run')
        _text(self.item_key)
        _id(self.corpus_id, 'corpus')
        _path(self.relative_path)
        if self.expected_sha256 is not None:
            _sha(self.expected_sha256)
        if self.file_id is not None:
            _id(self.file_id, 'file')
        if self.status not in ('pending', 'processed', 'skipped', 'failed'):
            raise ValueError('Invalid item status')
        if self.status == 'processed' and self.file_id is None:
            raise ValueError('Processed item requires physical file')
        if self.reason_code is not None and not re.fullmatch('[a-z][a-z0-9_]{0,63}', self.reason_code):
            raise ValueError('Invalid reason code')
        if self.status in ('failed', 'skipped') and self.reason_code is None:
            raise ValueError('Failed/skipped item requires reason')
        if self.error_detail is not None:
            if self.status != 'failed':
                raise ValueError('Error detail belongs only to failed items')
            # Free-form diagnostics can contain PII even without paths or tracebacks.
            object.__setattr__(self, 'error_detail', 'Details omitted; see reason_code.')
