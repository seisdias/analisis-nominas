import re

from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class ExcelticParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        m_fn = re.search(r'(\d{4})(\d{2})', filename)
        if m_fn:
            anio, mes = int(m_fn.group(1)), int(m_fn.group(2))
        else:
            raise ValueError("Missing payroll period")
        periodo = f"{anio}-{mes:02d}"

        for pattern in (r'TOTAL\s+DEVENGO[^\d]*[\d.,]+', r'TOTAL\s+DEDU[^\d]*[\d.,]+', r'(?:LIQUIDO\s+)?TOTAL\s+A\s+PERCIBIR[^\d]*[\d.,]+'):
            if not re.search(pattern, text, re.I):
                raise ValueError("Missing payroll totals")

        # Búsqueda de importes monetarios al final de palabras clave
        def extract_amount(pattern, default=0.0):
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = m.group(1).replace('.', '').replace(',', '.')
                try:
                    return float(val)
                except ValueError:
                    pass
            return default

        # Captura de campos clave
        sb = extract_amount(r'SALARIO\s+BASE[^\d]*([\d\.,]+)')
        pc = extract_amount(r'PLUS\s+CONVENIO[^\d]*([\d\.,]+)')
        pe = extract_amount(r'P\.?P\.?\s*EXTRA[^\d]*([\d\.,]+)')

        # Buscar el líquido percibido (probar varios patrones)
        liq = extract_amount(r'LIQUIDO\s+TOTAL\s+A\s+PERCIBIR[^\d]*([\d\.,]+)')
        if liq == 0.0:
            liq = extract_amount(r'TOTAL\s+A\s+PERCIBIR[^\d]*([\d\.,]+)')

        tot_dev = extract_amount(r'TOTAL\s+DEVENGO[^\d]*([\d\.,]+)')
        tot_ded = extract_amount(r'TOTAL\s+DEDU[^\d]*([\d\.,]+)')

        if tot_dev == 0.0 and liq > 0.0:
            tot_dev = liq
        if tot_ded == 0.0:
            tot_ded = max(0.0, tot_dev - liq)

        comp = max(0.0, tot_dev - (sb + pc + pe))

        return self._validate(Nomina(
            id=f"{periodo}-EXCELTIC",
            anio=anio,
            mes=mes,
            periodo=periodo,
            empresa="Exceltic",
            cif="B84242767",
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
