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

    # Original PDF stream order, including real glyph coordinates.
    characters: tuple[ExtractedWord, ...] | None = None
    # Explicit pages, including blank ones; absent in legacy DTOs.
    pages: tuple["ExtractedDocument", ...] | None = None
