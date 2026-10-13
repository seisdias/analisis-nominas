"""Portable selections contain synthetic identifiers only."""
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from src.alten_resolutions import VersionResolution, decode_resolutions, encode_resolutions


def valid():
    return VersionResolution('document', 'v1', 'Reviewed', ('v2', 'v1'))


def test_canonical_immutable_roundtrip():
    item = valid()
    assert item.expected_version_ids == ('v1', 'v2')
    assert decode_resolutions(encode_resolutions((item,))) == (item,)
    assert encode_resolutions((item,)) == encode_resolutions((replace(item, expected_version_ids=('v1', 'v2')),))
    with pytest.raises(FrozenInstanceError):
        item.reason = 'changed'


@pytest.mark.parametrize('field,value', [
    ('document_id', ''), ('document_id', 1), ('version_id', ' '), ('reason', None),
    ('reason', '\x00'), ('expected_version_ids', ()), ('expected_version_ids', []),
    ('expected_version_ids', ('v1', 'v1')), ('expected_version_ids', ('v2',)),
    ('expected_version_ids', ('v1', 1)),
])
def test_invalid_contract(field, value):
    with pytest.raises(ValueError):
        replace(valid(), **{field: value})


@pytest.mark.parametrize('change', ['version', 'bool', 'extra', 'row_extra', 'duplicate', 'inventory_type', 'reason_type'])
def test_strict_json(change):
    raw = json.loads(encode_resolutions((valid(),)))
    if change == 'version':
        raw['version'] = 2
    elif change == 'bool':
        raw['version'] = True
    elif change == 'extra':
        raw['extra'] = 1
    elif change == 'row_extra':
        raw['resolutions'][0]['extra'] = 1
    elif change == 'duplicate':
        raw['resolutions'] *= 2
    elif change == 'inventory_type':
        raw['resolutions'][0]['expected_version_ids'] = 'v1'
    else:
        raw['resolutions'][0]['reason'] = 42
    with pytest.raises(ValueError):
        decode_resolutions(json.dumps(raw).encode())


@pytest.mark.parametrize('data', [b'{', b'{"version":1,"version":1}', b'NaN'])
def test_invalid_json(data):
    with pytest.raises(ValueError):
        decode_resolutions(data)


def test_duplicate_encode():
    with pytest.raises(ValueError):
        encode_resolutions((valid(), valid()))


def test_empty_bundle_requires_omitting_optional_input():
    with pytest.raises(ValueError, match='empty'):
        decode_resolutions(b'{"contract":"alten-version-resolutions","version":1,"resolutions":[]}')
