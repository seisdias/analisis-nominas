"""Namespaced string identifiers, independent of entity and storage policies."""

import re
from enum import StrEnum


class IdNamespace(StrEnum):
    PERSON = "person"
    EMPLOYER = "employer"
    FILE = "file"
    DOCUMENT = "document"
    VERSION = "version"
    EXTRACTION = "extraction"
    FACT = "fact"
    ASSESSMENT = "assessment"
    OBSERVATION = "observation"
    RULE = "rule"
    DERIVED = "derived"


def validate_namespace(namespace: str) -> None:
    if not isinstance(namespace, str):
        raise TypeError("Namespace must be text")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", namespace):
        raise ValueError("Invalid identifier namespace")


class CanonicalId(str):
    """Validated immutable '<namespace>:sha256:<64 lowercase hexadecimal digits>'.

    This validates identity syntax, not entity existence or semantic identity.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> "CanonicalId":
        if not isinstance(value, str):
            raise TypeError("Identifier must be text")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}:sha256:[0-9a-f]{64}", value):
            raise ValueError("Invalid canonical identifier")
        return super().__new__(cls, value)

    @property
    def namespace(self) -> str:
        return self.split(":", 1)[0]

    @property
    def digest(self) -> str:
        return self.rsplit(":", 1)[1]


class ReproducibilityConflict(ValueError):
    """The same deterministic identity was associated with different content.

    Future repositories must raise this instead of overwriting conflicting data.
    No comparison or persistence policy is imposed by this exception.
    """
