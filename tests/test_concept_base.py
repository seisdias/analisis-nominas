"""Compatibility and JSON payload regression for explicit concept bases."""
import json

import pytest

from src.models.nomina import ConceptoNomina, Nomina
from src.services.database_service import DatabaseService


def _document(concept: ConceptoNomina) -> Nomina:
    return Nomina(id="synthetic-base", anio=2099, mes=1, periodo="2099-01",
                  empresa="Synthetic", cif="TEST", conceptos=[concept])


def test_legacy_constructor():
    concept = ConceptoNomina("T", "Synthetic", "otro", "deducciones", 10, "10,00")
    assert concept.base is None


def test_old_payload_without_base():
    old = _document(ConceptoNomina("T", "Synthetic", "otro", "deducciones", 10, "10,00")).to_dict()
    del old["conceptos"][0]["base"]
    restored = Nomina.from_dict(json.loads(json.dumps(old)))
    assert restored.conceptos[0].base is None


@pytest.mark.parametrize("base", [None, 0.0, 1234.56])
def test_base_json_and_database_payload_roundtrip(base):
    concept = ConceptoNomina("T", "Synthetic", "cotizacion", "deducciones", 10, "10,00",
                             porcentaje=5, base=base)
    assert concept.unidades is concept.precio is None
    doc = _document(concept)
    payload = json.dumps(doc.to_dict())
    assert Nomina.from_dict(json.loads(payload)) == doc
    # Existing payload storage, isolated in memory; no schema changes.
    db = DatabaseService(":memory:")
    try:
        db.init_db()
        db.guardar_documento(doc)
        row = db.obtener_todos()[0]
        assert Nomina.from_dict(json.loads(row["payload"])) == doc
        assert row["conceptos"][0]["base"] == base
    finally:
        assert db._shared_conn is not None
        db._shared_conn.close()
