from src.models import (
    CertificadoRetenciones,
    DocumentoLaboral,
    Finiquito,
    Nomina,
    TipoDocumento,
)


def test_documento_laboral_base_creation():
    doc = DocumentoLaboral(
        id="2024-01-BASE",
        anio=2024,
        mes=1,
        periodo="2024-01",
        empresa="Empresa Test",
        cif="B12345678",
        tipo=TipoDocumento.NOMINA_ORDINARIA
    )
    assert doc.id == "2024-01-BASE"
    assert doc.tipo == TipoDocumento.NOMINA_ORDINARIA
    assert doc.es_procesable is True

def test_nomina_especializacion():
    nomina = Nomina(
        id="2024-01-NOMINA",
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
    assert nomina.total_deducciones == 600.0  # Devengado (2500) - Líquido (1900)
    assert nomina.liquido_percibir == 1900.0

def test_finiquito_especializacion():
    finiquito = Finiquito(
        id="2024-05-FINIQUITO",
        anio=2024,
        mes=5,
        periodo="2024-05",
        empresa="Exceltic",
        cif="B84242767",
        tipo=TipoDocumento.FINIQUITO,
        indemnizacion=1500.0,
        vacaciones_no_disfrutadas=300.0,
        total_devengado=1800.0,
        liquido_percibir=1600.0
    )
    assert finiquito.tipo == TipoDocumento.FINIQUITO
    assert finiquito.indemnizacion == 1500.0

def test_certificado_retenciones_especializacion():
    cert = CertificadoRetenciones(
        id="2023-CERT",
        anio=2023,
        mes=12,
        periodo="2023-12",
        empresa="Altran",
        cif="B80428972",
        tipo=TipoDocumento.CERTIFICADO_RETENCIONES,
        retribuciones_integras=35000.0,
        retenciones_practicadas=5200.0
    )
    assert cert.retribuciones_integras == 35000.0