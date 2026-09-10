import re

from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class AltranParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        m_fn = re.search(r'(\d{4})_?(\d{2})', filename)
        if m_fn:
            anio, mes = int(m_fn.group(1)), int(m_fn.group(2))
        else:
            raise ValueError("Missing payroll period")
        periodo = f"{anio}-{mes:02d}"

        if not re.search(r'Totales\s+[\d.,]+\s+[\d.,]+', text) or not re.search(r'Líquido a percibir\s+[\d.,]+', text, re.I):
            raise ValueError("Missing payroll totals")

        def extract_amount(pattern, default=0.0):
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = m.group(1).replace('.', '').replace(',', '.')
                try:
                    return float(val)
                except ValueError:
                    pass
            return default

        sb = extract_amount(r'Salario Base\s+[\d\.,]+\s+[\d\.,]+\s+([\d\.,]+)')
        pc = extract_amount(r'Plus Convenio\s+[\d\.,]+\s+[\d\.,]+\s+([\d\.,]+)')
        pe = extract_amount(r'Parte Proporcional Pagas Extras\s+([\d\.,]+)')

        m_tot = re.search(r'Totales\s+([\d\.,]+)\s+([\d\.,]+)', text)
        if m_tot:
            tot_dev = float(m_tot.group(1).replace('.', '').replace(',', '.'))
            tot_ded = float(m_tot.group(2).replace('.', '').replace(',', '.'))
        else:
            tot_dev, tot_ded = 0.0, 0.0

        liq = extract_amount(r'Líquido a percibir\s+([\d\.,]+)')
        if liq == 0.0:
            liq = max(0.0, tot_dev - tot_ded)

        comp = max(0.0, tot_dev - (sb + pc + pe))

        return self._validate(Nomina(
            id=f"{periodo}-ALTRAN",
            anio=anio,
            mes=mes,
            periodo=periodo,
            empresa="Altran",
            cif="B80428972",
            categoria=None,
            grupo_cotizacion=None,
            salario_base=round(sb, 2),
            plus_convenio=round(pc, 2),
            complementos=round(comp, 2),
            prorrata_pagas_extra=round(pe, 2),
            total_devengado=round(tot_dev, 2),
            descuento_seguridad_social=0.0,
            irpf_porcentaje=0.0,
            irpf_importe=0.0,
            total_deducir=round(tot_ded, 2),
            liquido_percibir=round(liq, 2),
            base_irpf=round(tot_dev, 2),
            observaciones=f"Procesado desde {filename}"
        ))
