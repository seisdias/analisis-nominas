# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Literal, Optional

from src.models.documento_laboral import DocumentoLaboral, TipoDocumento


@dataclass
class ConceptoNomina:
    """One printed economic entry; repeated codes and both columns are retained.

    Totals in Nomina remain independent printed values, never reconstructed from
    this breakdown. importe_texto preserves extraction notation for inspection.
    """

    codigo: str
    concepto: str
    categoria: str
    columna: Literal["devengos", "deducciones"]
    importe: float
    importe_texto: str
    atraso: bool = False
    porcentaje: Optional[float] = None
    unidades: Optional[float] = None
    precio: Optional[float] = None


@dataclass
class Nomina(DocumentoLaboral):
    # Campos opcionales específicos
    categoria: Optional[str] = None
    grupo_cotizacion: Optional[str] = None

    # Devengos
    salario_base: float = 0.0
    plus_convenio: float = 0.0
    complementos: float = 0.0
    prorrata_pagas_extra: Optional[float] = 0.0
    total_devengado: float = 0.0

    # Deducciones
    descuento_seguridad_social: Optional[float] = 0.0
    irpf_porcentaje: Optional[float] = 0.0
    irpf_importe: Optional[float] = 0.0
    otras_deducciones: Optional[float] = 0.0
    total_deducir: float = 0.0

    # Totales y bases
    liquido_percibir: float = 0.0
    base_ss_comunes: Optional[float] = 0.0
    base_irpf: Optional[float] = 0.0

    # ISO dates fit the existing JSON payload; older documents need no migration.
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None

    conceptos: list[ConceptoNomina] = field(default_factory=list)

    @property
    def total_deducciones(self) -> float:
        """Calcula el total de deducciones por diferencia."""
        return round(self.total_devengado - self.liquido_percibir, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Convierte la entidad a un diccionario estándar."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Nomina":
        """Instancia un objeto Nomina desde un diccionario."""
        values = dict(data)
        if "tipo" in values:
            values["tipo"] = TipoDocumento(values["tipo"])
        if "conceptos" in values:
            values["conceptos"] = [ConceptoNomina(**item) if isinstance(item, dict) else item
                                   for item in values["conceptos"]]
        return cls(**values)
