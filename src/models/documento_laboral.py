# -*- coding: utf-8 -*-
from dataclasses import dataclass
from enum import Enum


class TipoDocumento(str, Enum):
    NOMINA_ORDINARIA = "NOMINA_ORDINARIA"
    PAGA_EXTRA = "PAGA_EXTRA"
    VARIABLE_BONUS = "VARIABLE_BONUS"
    FINIQUITO = "FINIQUITO"
    CERTIFICADO_RETENCIONES = "CERTIFICADO_RETENCIONES"
    MANUAL_ESCANEADO = "MANUAL_ESCANEADO"


@dataclass
class DocumentoLaboral:
    id: str
    anio: int
    mes: int
    periodo: str
    empresa: str
    cif: str
    tipo: TipoDocumento = TipoDocumento.NOMINA_ORDINARIA
    es_procesable: bool = True
    observaciones: str = ""


@dataclass
class Finiquito(DocumentoLaboral):
    indemnizacion: float = 0.0
    vacaciones_no_disfrutadas: float = 0.0
    parte_proporcional_paga_extra: float = 0.0
    total_devengado: float = 0.0
    total_deducir: float = 0.0
    liquido_percibir: float = 0.0


@dataclass
class CertificadoRetenciones(DocumentoLaboral):
    retribuciones_integras: float = 0.0
    gastos_deducibles: float = 0.0
    retenciones_practicadas: float = 0.0