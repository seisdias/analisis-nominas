# -*- coding: utf-8 -*-
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from src.models.documento_laboral import DocumentoLaboral, TipoDocumento


@dataclass
class Nomina(DocumentoLaboral):
    # Campos opcionales específicos
    categoria: Optional[str] = None
    grupo_cotizacion: Optional[str] = None

    # Devengos
    salario_base: float = 0.0
    plus_convenio: float = 0.0
    complementos: float = 0.0
    prorrata_pagas_extra: float = 0.0
    total_devengado: float = 0.0

    # Deducciones
    descuento_seguridad_social: float = 0.0
    irpf_porcentaje: float = 0.0
    irpf_importe: float = 0.0
    otras_deducciones: float = 0.0
    total_deducir: float = 0.0

    # Totales y bases
    liquido_percibir: float = 0.0
    base_ss_comunes: float = 0.0
    base_irpf: float = 0.0

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
        return cls(**values)