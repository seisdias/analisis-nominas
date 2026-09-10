# -*- coding: utf-8 -*-
import re

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class InsisParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        meses = {
            "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
            "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
            "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12
        }

        # 1. Periodo
        match_periodo = re.search(r'P\s*e\s*r\s*í\s*o\s*d\s*o.*?DE\s+([A-Z]+)\s+DE\s+(\d{4})', text, re.IGNORECASE)
        if match_periodo:
            mes_str = match_periodo.group(1).upper()
            mes = meses.get(mes_str, 0)
            anio = int(match_periodo.group(2))
        else:
            raise ValueError("Missing payroll period")

        periodo_str = f"{anio}-{mes:02d}"

        for label in ("TOTALDEVENGADO", "TOTALADEDUCIR", "LIQUIDOTOTALAPERCIBIR"):
            if label not in re.sub(r"[^A-Z]", "", text.upper()):
                raise ValueError("Missing payroll totals")

        # Detectar paga extra real (solamente si aparece "PAGA EXTRAORDINARIA" explícitamente en el título/concepto)
        es_extra = "PAGA EXTRAORDINARIA" in text.upper() or "GRATIFICACION EXTRAORDINARIA" in text.upper()
        doc_id = f"{periodo_str}-INSIS{'-EXTRA' if es_extra else ''}"

        # Helper para extraer e igualar a 2 decimales
        def parse_clean_float(pattern, default=0.0, required=False):
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_str = match.group(1)
                cleaned = re.sub(r'[\.\s]', '', raw_str).replace(',', '.')
                try:
                    return round(float(cleaned), 2)
                except ValueError:
                    if required:
                        raise ValueError("Invalid payroll total") from None
                    return default
            if required:
                raise ValueError("Missing payroll total")
            return default

        # 2. Devengos
        salario_base = parse_clean_float(r'Sala\s*rio\s*B\s*a\s*se\s*([\d\.,\s]+)')
        plus_convenio = parse_clean_float(r'P\.CONVENIO\s*([\d\.,\s]+)')
        incentivos = parse_clean_float(r'INCENTIVOS\s*([\d\.,\s]+)')
        transporte = parse_clean_float(r'TRANSPORTE\s*([\d\.,\s]+)')
        complementos = round(incentivos + transporte, 2)

        total_devengado = parse_clean_float(r'T\s*O\s*T\s*A\s*L\s*D\s*E\s*V\s*E\s*N\s*G\s*A\s*D\s*O[\.\s]*([\d\.,\s]+)', required=True)
        if total_devengado == 0.0:
            total_devengado = round(salario_base + plus_convenio + complementos, 2)

        # 3. Deducciones
        descuento_ss = parse_clean_float(r'T\s*O\s*T\s*AL\s*A\s*P\s*O\s*RT\s*A\s*C\s*IO\s*N\s*E\s*S[\.\s]*([\d\.,\s]+)')

        match_irpf = re.search(r'Impu\s*e\s*sto.*?([\d,]+)\s+([\d\.,\s]+)', text)
        if match_irpf:
            irpf_porcentaje = round(float(match_irpf.group(1).replace(',', '.')), 2)
            cleaned_irpf = re.sub(r'[\.\s]', '', match_irpf.group(2)).replace(',', '.')
            irpf_importe = round(float(cleaned_irpf), 2)
        else:
            irpf_porcentaje, irpf_importe = 0.0, 0.0

        anticipos = parse_clean_float(r'Antic\s*ip\s*os[\.\s]*([\d\.,\s]+)')

        total_deducir = parse_clean_float(r'T\s*O\s*T\s*A\s*L\s*A\s*D\s*E\s*D\s*U\s*C\s*I\s*R[\.\s]*([\d\.,\s]+)', required=True)
        if total_deducir == 0.0:
            total_deducir = round(descuento_ss + irpf_importe + anticipos, 2)

        # 4. Líquido
        liquido_percibir = parse_clean_float(
            r'L\s*I\s*Q\s*U\s*ID\s*O\s*T\s*O\s*T\s*A\s*L\s*A\s*P\s*E\s*R\s*C\s*IB\s*I\s*R.*?PTA\s+([\d\.,\s]+)', required=True)
        if liquido_percibir == 0.0:
            liquido_percibir = round(total_devengado - total_deducir, 2)

        # 5. Prorrata y Bases
        prorrata_val = parse_clean_float(
            r'Prorr\s*at\s*a\s*p\s*a\s*ga\s*s\s*E\s*xt\s*ra\s*or\s*din\s*a\s*ri\s*a\s*s[\.\s]*([\d\.,\s]+)')

        base_ss = parse_clean_float(r'T\s*O\s*T\s*A\s*L\s*\.[\.\s]*([\d\.,\s]+)')
        if base_ss == 0.0:
            base_ss = parse_clean_float(r'contingencias\s+profesionales.*?([\d\.,\s]+)')

        base_irpf = parse_clean_float(r'Base\s+suj\s*et\s*a\s*a\s*re\s*te\s*nc\s*ió\s*n[\.\s]*([\d\.,\s]+)')
        if base_irpf == 0.0:
            base_irpf = total_devengado

        return self._validate(Nomina(
            id=doc_id,
            tipo=TipoDocumento.PAGA_EXTRA if es_extra else TipoDocumento.NOMINA_ORDINARIA,
            anio=anio,
            mes=mes,
            periodo=periodo_str,
            empresa="INTELIGENCIA SISTEMATICA 4, S.L.",
            cif="B84225283",
            categoria=None,
            grupo_cotizacion=None,
            salario_base=salario_base,
            plus_convenio=plus_convenio,
            complementos=complementos,
            prorrata_pagas_extra=prorrata_val,
            total_devengado=total_devengado,
            descuento_seguridad_social=descuento_ss,
            irpf_porcentaje=irpf_porcentaje,
            irpf_importe=irpf_importe,
            otras_deducciones=anticipos,
            total_deducir=total_deducir,
            liquido_percibir=liquido_percibir,
            base_ss_comunes=base_ss,
            base_irpf=base_irpf,
            observaciones=f"Procesado desde {filename}"
        ))
