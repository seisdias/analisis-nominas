import pytest

from src.models import (
    CertificadoRetenciones,
    Nomina,
    TipoDocumento,
)
from src.services.database_service import DatabaseService


@pytest.fixture
def db_service():
    # Instancia en memoria para pruebas ultrarrápidas y aisladas
    service = DatabaseService(db_path=":memory:")
    service.init_db()
    return service


def test_save_and_retrieve_nomina(db_service):
    nomina = Nomina(
        id="2024-01-ALTEN",
        anio=2024,
        mes=1,
        periodo="2024-01",
        empresa="Alten",
        cif="A28250271",
        tipo=TipoDocumento.NOMINA_ORDINARIA,
        salario_base=2000.0,
        total_devengado=2500.0,
        liquido_percibir=1900.0
    )
    db_service.guardar_documento(nomina)

    docs = db_service.obtener_documentos_por_empresa("Alten")
    assert len(docs) == 1
    assert docs[0]["id"] == "2024-01-ALTEN"
    assert docs[0]["liquido_percibir"] == 1900.0


def test_save_and_retrieve_certificado(db_service):
    cert = CertificadoRetenciones(
        id="2023-CERT-ALTRAN",
        anio=2023,
        mes=12,
        periodo="2023-12",
        empresa="Altran",
        cif="B80428972",
        tipo=TipoDocumento.CERTIFICADO_RETENCIONES,
        retribuciones_integras=35000.0,
        retenciones_practicadas=5200.0
    )
    db_service.guardar_documento(cert)

    certificados = db_service.obtener_certificados()
    assert len(certificados) == 1
    assert certificados[0]["retribuciones_integras"] == 35000.0


def test_reset_db_rapido(db_service):
    nomina = Nomina(
        id="TEST-RESET",
        anio=2024,
        mes=1,
        periodo="2024-01",
        empresa="Test",
        cif="B00000000"
    )
    db_service.guardar_documento(nomina)
    assert len(db_service.obtener_todos()) == 1

    db_service.reset_db()
    assert len(db_service.obtener_todos()) == 0