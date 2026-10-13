"""Explicit, auditable ALTEN document-version selections."""

import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class VersionResolution:
    """Human-reviewed selection of one version of a logical document."""

    document_id: str
    version_id: str
    reason: str
    expected_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() or '\x00' in value
               for value in (self.document_id, self.version_id, self.reason)):
            raise ValueError('ALTEN resolution fields must be nonempty strings')
        versions = self.expected_version_ids
        if (not isinstance(versions, tuple) or not versions
                or any(not isinstance(v, str) or not v.strip() or '\x00' in v for v in versions)
                or len(set(versions)) != len(versions)
                or self.version_id not in versions):
            raise ValueError('ALTEN resolution has an invalid version inventory')
        object.__setattr__(self, 'expected_version_ids', tuple(sorted(versions)))


def encode_resolutions(resolutions: tuple[VersionResolution, ...]) -> bytes:
    """Strict standalone selection contract, distinct from fact acknowledgements."""
    if not resolutions:
        raise ValueError('ALTEN resolution bundle must not be empty')
    if len({r.document_id for r in resolutions}) != len(resolutions):
        raise ValueError('Multiple ALTEN resolutions for one document')
    return json.dumps({'contract': 'alten-version-resolutions', 'version': 1,
                       'resolutions': [asdict(r) for r in sorted(resolutions, key=lambda r: r.document_id)]},
                      ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate resolution JSON key')
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise ValueError('Resolution JSON does not accept floating/nonfinite numbers')


def decode_resolutions(data: bytes) -> tuple[VersionResolution, ...]:
    raw = json.loads(data, object_pairs_hook=_pairs, parse_float=_reject_number,
                     parse_constant=_reject_number)
    if (not isinstance(raw, dict) or set(raw) != {'contract', 'version', 'resolutions'}
            or raw['contract'] != 'alten-version-resolutions' or type(raw['version']) is not int
            or raw['version'] != 1 or not isinstance(raw['resolutions'], list)):
        raise ValueError('Unsupported ALTEN resolution contract')
    result = []
    for row in raw['resolutions']:
        if (not isinstance(row, dict) or set(row) != set(VersionResolution.__dataclass_fields__)
                or not isinstance(row['expected_version_ids'], list)):
            raise ValueError('Invalid ALTEN resolution record')
        result.append(VersionResolution(**dict(row, expected_version_ids=tuple(row['expected_version_ids']))))
    encode_resolutions(tuple(result))
    return tuple(sorted(result, key=lambda r: r.document_id))
