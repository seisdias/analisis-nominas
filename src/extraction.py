"""PDF extraction evidence, independent of payroll/domain models."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedWord:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int  # One-based PDF page; coordinates are local to that page.


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    # None means layout was not requested; () means no words were extracted.
    words: tuple[ExtractedWord, ...] | None = None
