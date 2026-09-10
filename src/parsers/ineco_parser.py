# -*- coding: utf-8 -*-
import re

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class InecoParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        # 1. Periodo explícito del documento
        match_periodo = re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+\d{2}\.\d{2}\.\d{4}', text)
        if match_periodo:
            mes = int(match_periodo.group(2))
            anio = int(match_periodo.group(3))
        else:
            raise ValueError("Missing payroll period")

        periodo_str = f"{anio}-{mes:02d}"

        if not re.search(r'Total\s+Devengos\s+Total\s+Deducciones', text) or not re.search(r'Líquido\s+a\s+percibir:\s*[\d.,]+', text):
            raise ValueError("Missing payroll totals")

        # Identificador del documento
        if "FINIQUITO" in text.upper():
            raise ValueError("Settlement documents are not supported yet")
        es_extra = "PAGA EXTRA" in text.upper()
        doc_id = f"{periodo_str}-INECO{'-EXTRA' if es_extra else ''}"

        # Helper para extracción numérica
        def parse_float(pattern, group_idx=1, default=0.0, flags=0, required=False):
            match = re.search(pattern, text, flags=flags)
            if match:
                raw_str = match.group(group_idx).strip()
                if raw_str:
                    try:
                        return float(raw_str.replace('.', '').replace(',', '.'))
                    except ValueError:
                        if required:
                            raise ValueError("Invalid payroll total") from None
                        return default
            if required:
                raise ValueError("Missing payroll total")
            return default

        # 2. Devengos
        salario_base = parse_float(r'9001\s+Salario\s+Base\s+([\d\.,]+)')
        plus_convenio = parse_float(r'9002\s+Plus\s+Convenio\s+([\d\.,]+)')
        comp_salarial = parse_float(r'9004\s+Comp\.Salarial\s+([\d\.,]+)')

        # Extracción de Devengos y Deducciones Totales
        # Captura la línea con los valores numéricos bajo la cabecera de totales
        totales_match = re.search(
            r'Total\s+Devengos\s+Total\s+Deducciones\s*\n.*?\b([\d\.,]+)\s+([\d\.,]+)\s*$',
            text, flags=re.MULTILINE)
        if totales_match:
            total_devengado = float(totales_match.group(1).replace('.', '').replace(',', '.'))
            total_deducir = float(totales_match.group(2).replace('.', '').replace(',', '.'))
        else:
            raise ValueError("Missing payroll totals")

        # 3. Deducciones
        irpf_porcentaje = parse_float(r'/401\s+Retención\s+IRPF\s+([\d\.,]+)')
        irpf_importe = parse_float(r'/401\s+Retención\s+IRPF\s+[\d\.,]+\s+([\d\.,]+)')

        dto_accidente = parse_float(r'T002\s+Dto\s+Base\s+Accidente\s+[\d\.,]+\s+([\d\.,]+)')
        dto_cc = parse_float(r'/350\s+Trab\.cont\.comunes\s+[\d\.,]+\s+([\d\.,]+)')
        descuento_ss = round(dto_accidente + dto_cc, 2)

        if descuento_ss == 0.0 and total_deducir > 0:
            descuento_ss = round(total_deducir - irpf_importe, 2)

        # 4. Líquido
        liquido_percibir = parse_float(r'Líquido\s+a\s+percibir:\s*([\d\.,]+)', required=True)
        if liquido_percibir == 0.0 and total_devengado > 0:
            liquido_percibir = round(total_devengado - total_deducir, 2)

        # 5. Prorrata y Bases
        prorrata_val = parse_float(r'Prorratas\s+pagas\s*\n?\s*extras\s*:\s*([\d\.,]+)')
        if prorrata_val == 0.0:
            prorrata_val = parse_float(r'extras\s*:\s*([\d\.,]+)')

        base_ss = parse_float(r'Total\s+Base:\s*([\d\.,]+)')
        base_irpf = total_devengado

        # 6. Categoría y Grupo
        cat_match = re.search(r'\d{2}/\d{2}/\d{4}\s+\d{2}/\d{2}/\d{4}\s+(.*?)\n', text)
        categoria = cat_match.group(1).strip() if cat_match else None

        grupo_match = re.search(r'Nº\s+Afiliación.*?\n.*?\s+(\d{2})\s+\d{3}', text)
        grupo_cot = grupo_match.group(1) if grupo_match else None

        otras_ded = round(total_deducir - descuento_ss - irpf_importe, 2)
        if otras_ded < 0:
            otras_ded = 0.0

        return self._validate(Nomina(
            id=doc_id,
            tipo=TipoDocumento.PAGA_EXTRA if es_extra else TipoDocumento.NOMINA_ORDINARIA,
            anio=anio,
            mes=mes,
            periodo=periodo_str,
            empresa="Ingeniería y Economía del Transporte S.M.E. M.P. S.A.",
            cif="A28220168",
            categoria=categoria,
            grupo_cotizacion=grupo_cot,
            salario_base=salario_base,
            plus_convenio=plus_convenio,
            complementos=comp_salarial,
            prorrata_pagas_extra=prorrata_val,
            total_devengado=total_devengado,
            descuento_seguridad_social=descuento_ss,
            irpf_porcentaje=irpf_porcentaje,
            irpf_importe=irpf_importe,
            otras_deducciones=otras_ded,
            total_deducir=total_deducir,
            liquido_percibir=liquido_percibir,
            base_ss_comunes=base_ss,
            base_irpf=base_irpf,
            observaciones=f"Procesado desde {filename}"
        ))
