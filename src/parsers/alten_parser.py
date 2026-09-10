import re

from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class AltenParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        m_fn = re.search(r'(\d{4})(\d{2})', filename)
        if m_fn:
            anio, mes = int(m_fn.group(1)), int(m_fn.group(2))
        else:
            raise ValueError("Missing payroll period")
        periodo = f"{anio}-{mes:02d}"

        if not re.search(r'TOTAL\s+DEVENGADO\s+TOTAL\s+DEDUCCIONES\s+[\d.,]+\s+[\d.,]+', text, re.I):
            raise ValueError("Missing payroll totals")

        # Eliminar espacio entre dígitos y comas/puntos que alteren los números
        clean_text = re.sub(r'(\d)\s+([\.,])', r'\1\2', text)
        clean_text = re.sub(r'([\.,])\s+(\d)', r'\1\2', clean_text)

        # Captura de líquido con expresión flexible
        liq = 0.0
        patterns_liq = [
            r'L\s*I\s*Q\s*U\s*I\s*D\s*O\s+A\s+P\s*E\s*R\s*C\s*I\s*B\s*I\s*R[^\d]*([\d\.,]+)',
            r'LIQUIDO\s+A\s+PERCIBIR[^\d]*([\d\.,]+)',
            r'NETO\s+A\s+PERCIBIR[^\d]*([\d\.,]+)'
        ]

        for p in patterns_liq:
            m = re.search(p, clean_text, re.IGNORECASE)
            if m:
                try:
                    liq = float(m.group(1).replace('.', '').replace(',', '.'))
                    if liq > 0:
                        break
                except ValueError:
                    continue

        if not any(re.search(pattern, clean_text, re.I) for pattern in patterns_liq):
            raise ValueError("Missing net payroll total")

        # Totales devengados y deducciones
        tot_dev, tot_ded = liq, 0.0
        m_tot = re.search(r'TOTAL\s+DEVENGADO\s+TOTAL\s+DEDUCCIONES\s*[\n\s]*([\d\.,]+)\s+([\d\.,]+)', clean_text, re.IGNORECASE)
        if m_tot:
            try:
                tot_dev = float(m_tot.group(1).replace('.', '').replace(',', '.'))
                tot_ded = float(m_tot.group(2).replace('.', '').replace(',', '.'))
            except ValueError:
                pass

        return self._validate(Nomina(
            id=f"{periodo}-ALTEN",
            anio=anio,
            mes=mes,
            periodo=periodo,
            empresa="Alten",
            cif="A28250271",
            categoria=None,
            grupo_cotizacion=None,
            salario_base=0.0,
            plus_convenio=0.0,
            complementos=0.0,
            prorrata_pagas_extra=0.0,
            total_devengado=round(tot_dev, 2),
            descuento_seguridad_social=0.0,
            irpf_porcentaje=0.0,
            irpf_importe=0.0,
            total_deducir=round(tot_ded, 2),
            liquido_percibir=round(liq, 2),
            base_irpf=round(tot_dev, 2),
            observaciones=f"Procesado desde {filename}"
        ))
