"""Synthetic geometry verifies the scoped image contract, not OCR heuristics."""

from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest

from src.canonical.values import CanonicalValue, ExactDecimal, ValueState
from src.documentary_currency import EXCELTIC_REVISION, attest_exceltic_net


def evidence(monkeypatch, *, case="valid"):
    pixels = b"synthetic reviewed EUR glyph"
    monkeypatch.setattr("src.documentary_currency.EXCELTIC_EURO_SHA", sha256(pixels).hexdigest())

    def word(text, x0, x1, top=100, bottom=108):
        return dict(text=text, x0=x0, x1=x1, top=top, bottom=bottom)

    words = [
        word("LIQUIDO", 10, 40),
        word("TOTAL", 44, 68),
        word("A", 72, 77),
        word("PERCIBIR", 81, 120),
        word("1.234,56", 48, 90, 117, 127),
    ]
    image: dict[str, Any] = dict(
        x0=120,
        x1=131,
        top=111,
        bottom=132,
        srcsize=(18, 29),
        bits=8,
        colorspace=[SimpleNamespace(name="DeviceRGB")],
        imagemask=None,
        stream=SimpleNamespace(attrs={}, get_data=lambda: pixels),
    )
    text = "LIQUIDO TOTAL A PERCIBIR\n1.234,56"
    value = CanonicalValue(state=ValueState.PRESENT, value=ExactDecimal(123456, 2))
    if case == "missing":
        images = []
    else:
        images = [image]
    if case == "wrong_field":
        image.update(top=200, bottom=221)
    if case == "wrong_symbol":
        image["stream"] = SimpleNamespace(attrs={}, get_data=lambda: b"unknown")
    if case == "mask":
        image["stream"].attrs["SMask"] = "another-image"
    if case == "conflict":
        text += "\nUSD"
    if case == "amount":
        words[-1]["text"] = "1.234,57"
    if case == "ambiguous":
        words.append(word("1.234,56", 12, 45, 117, 127))
    if case == "header":
        words[0]["text"] = "IMPORTE"
    if case == "unreliable":
        value = CanonicalValue(
            state=ValueState.UNRELIABLE,
            value=ExactDecimal(123456, 2),
            reason_code="test.unreliable",
        )
    if case == "unknown":
        value = CanonicalValue(state=ValueState.UNKNOWN, reason_code="test.unknown")
    page = SimpleNamespace(extract_words=lambda: words, images=images)
    return attest_exceltic_net(
        document_id="doc",
        version_id="version",
        extraction_id="ext",
        observation_id="obs",
        fact_id="fact",
        file_sha256="a" * 64,
        parser="ExcelticParser",
        revision=EXCELTIC_REVISION,
        page=1,
        value=value,
        text=text,
        page_data=page,
    )


def test_graphic_euro_attests_only_net_with_geometry_and_hash(monkeypatch):
    e = evidence(monkeypatch)
    assert e is not None and e.scope == "documentary_net" and e.currency.code == "EUR"
    assert e.symbol_box == (120, 111, 131, 132) and e.symbol_sha256
    assert e.amount == ExactDecimal(123456, 2)
    assert e.contract.startswith("exceltic")


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "wrong_field",
        "wrong_symbol",
        "mask",
        "conflict",
        "amount",
        "ambiguous",
        "header",
        "unreliable",
        "unknown",
    ],
)
def test_no_scope_no_image_or_bad_amount_does_not_attest(monkeypatch, case):
    assert evidence(monkeypatch, case=case) is None
