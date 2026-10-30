"""Synthetic ficha: completeness, arithmetic and certification stay distinct."""

from streamlit.testing.v1 import AppTest


def render(case):
    from dataclasses import replace

    from src.classification_view import render_classification
    from tests.unit.test_breakdown_completeness import source

    e = source(gross=10001 if case == "difference" else 10000)
    if case == "unverified":
        e = replace(e, content_hash="")
    render_classification(e)


def test_ficha_separate_completeness_and_arithmetic():
    app = AppTest.from_function(render, args=("difference",)).run()
    assert not app.exception
    table = next(df.value for df in app.dataframe if "Estado de completitud" in df.value)
    assert table["Comprobación"].tolist() == ["Devengos", "Deducciones", "Bruto/neto"]
    assert table.iloc[0]["Diferencia no explicada"] == "-0,01"
    assert table.iloc[1]["Diferencia no explicada"] == "0"
    assert any("no equivale" in c.value for c in app.caption)
    assert any("Hecho participante" in df.value for df in app.dataframe)


def test_ficha_does_not_display_calculated_zero_without_completeness():
    app = AppTest.from_function(render, args=("unverified",)).run()
    assert not app.exception
    table = next(df.value for df in app.dataframe if "Estado de completitud" in df.value)
    assert set(table["Total de componentes"]) == {"Sin cálculo"}
    assert set(table["Diferencia no explicada"]) == {"Sin cálculo"}
