"""Atomic documentary values, independent of legacy models and persistence."""

from dataclasses import dataclass, field

from src.canonical.evidence import _id, _text, _time, utc_now
from src.canonical.identifiers import CanonicalId
from src.canonical.serialization import deterministic_id
from src.canonical.values import CanonicalValue


def fact_id(extraction_id: str, fact_key: str) -> CanonicalId:
    _id(extraction_id, 'extraction')
    _text(fact_key)
    return deterministic_id('fact', {'extraction_id': str(extraction_id), 'fact_key': fact_key})


@dataclass(frozen=True, slots=True)
class FactDraft:
    fact_key: str
    value: CanonicalValue

    def __post_init__(self) -> None:
        _text(self.fact_key)
        if type(self.value) is not CanonicalValue:
            raise TypeError('Fact requires a CanonicalValue')


@dataclass(frozen=True, slots=True)
class DocumentaryFact:
    fact_id: str
    extraction_id: str
    fact_key: str
    value: CanonicalValue
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        FactDraft(self.fact_key, self.value)
        if self.fact_id != fact_id(self.extraction_id, self.fact_key):
            raise ValueError('Fact identity does not match extraction and key')
        _time(self.created_at)

    @classmethod
    def from_draft(cls, extraction_id: str, draft: FactDraft, *,
                   created_at: str | None = None) -> 'DocumentaryFact':
        return cls(fact_id(extraction_id, draft.fact_key), extraction_id, draft.fact_key,
                   draft.value, utc_now() if created_at is None else created_at)


@dataclass(frozen=True, slots=True)
class FactPage:
    fact_id: str
    page_number: int

    def __post_init__(self) -> None:
        _id(self.fact_id, 'fact')
        if type(self.page_number) is not int or not 0 < self.page_number < 2**63:
            raise ValueError('Positive signed-64-compatible physical page required')


@dataclass(frozen=True, slots=True)
class FactPageReference:
    """Complete persisted page reference, including its physical version scope."""

    fact_id: str
    version_id: str
    page_number: int

    def __post_init__(self) -> None:
        FactPage(self.fact_id, self.page_number)
        _id(self.version_id, 'version')
