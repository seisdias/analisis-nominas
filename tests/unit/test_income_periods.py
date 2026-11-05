from dataclasses import replace

import pytest

from src.income_evolution import MonthBasis, matching_periods


def test_matching_documentary_windows_keep_year_boundary():
    dec = MonthBasis("Empresa", (2024, 12), "Parser", "revision", None, (("1", "Base"),))
    jan = replace(dec, period=(2025, 1))
    windows = matching_periods([jan, dec])
    assert (
        len(windows) == 1 and windows[0]["Desde"] == "12/2024" and windows[0]["Hasta"] == "01/2025"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"company": "Otra"},
        {"period": (2025, 2)},
        {"revision": "otro"},
        {"currency": "EUR"},
        {"members": (("1", "Base"), ("1", "Base"))},
    ],
)
def test_different_composition_or_gap_breaks_window(change):
    dec = MonthBasis("Empresa", (2024, 12), "Parser", "revision", None, (("1", "Base"),))
    jan = replace(replace(dec, period=(2025, 1)), **change)
    assert not matching_periods([dec, jan])


def test_duplicate_month_never_bridges_a_gap():
    june = MonthBasis("Empresa", (2025, 6), "Parser", "revision", "EUR", (("1", "Base"),))
    july = replace(june, period=(2025, 7))
    august = replace(june, period=(2025, 8))
    assert not matching_periods([june, july, july, august])


@pytest.mark.parametrize(
    "end,multiple,expected",
    [("2025-06-30", False, 1), ("2025-06-29", False, 0), ("2025-06-30", True, 0)],
)
def test_comparable_basis_requires_whole_documentary_month(end, multiple, expected):
    from src.canonical.serialization import canonical_sha256
    from src.document_concepts import project_extraction
    from src.income_evolution import project_income
    from tests.unit.test_document_concepts import fact
    from tests.unit.test_income_evolution import fixture

    d, s, g = fixture()
    e = s.extractions[0]
    facts = [f.fact for f in e.facts] + [
        fact("nomina.fecha_inicio", "2025-06-01"),
        fact("nomina.fecha_fin", end),
    ]
    e = project_extraction(
        e.document_id,
        e.version_id,
        e.extraction_id,
        facts,
        extractor_name=e.extractor_name,
        extractor_revision=e.extractor_revision,
        content_hash=canonical_sha256({f.fact_key: f.value for f in facts}),
    )
    result = project_income(
        (d,), {d.document_id: replace(s, extractions=(e,))}, {}, [dict(g, Multipago=multiple)]
    )
    assert len(result.bases) == expected
    assert any(r["Componente"] == "Ordinario identificado (parcial)" for r in result.rows)
