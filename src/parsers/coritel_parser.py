import re

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class CoritelParser(BaseParser):
    EMPRESA = "Coritel, S.A."

    def parse(self, text: str, filename: str = "") -> Nomina:
        normalized = self._normalize_text(text)

        anio, mes, periodo = self._parse_period(normalized)

        categoria = self._parse_optional(
            normalized,
            r"CATEG/GRUPO PROF:\s*(.+)",
        )

        grupo_cotizacion = self._parse_optional(
            normalized,
            r"GRUPO COTIZACIÓN:\s*(\d+)",
        )

        cif = self._parse_required(
            normalized,
            r"CIF:\s*([A-Z]\d+)",
            "Missing Coritel CIF",
        )

        tipo = self._detect_document_type(normalized)

        total_devengado = self._parse_amount_required(
            normalized,
            r"TOTAL DEVENGADO.*?(\d[\d.,]*)",
            "Missing total devengado",
        )

        total_deducir = self._parse_amount_required(
            normalized,
            r"TOTAL A DEDUCIR.*?(\d[\d.,]*)",
            "Missing total deducir",
        )

        liquido_percibir = self._parse_amount_required(
            normalized,
            r"LIQUIDO TOTAL A PERCIBIR.*?(\d[\d.,]*)",
            "Missing liquido percibir",
        )

        salario_base = self._parse_amount_optional(
            normalized,
            r"^Salario base\s+(\d[\d.,]*)$",
        )

        plus_convenio = self._parse_amount_optional(
            normalized,
            r"^Plus convenio\s+(\d[\d.,]*)$",
        )

        complementos = self._parse_amount_optional(
            normalized,
            r"^Mejora voluntaria\s+(\d[\d.,]*)$",
        )

        descuento_seguridad_social = self._parse_amount_optional(
            normalized,
            r"TOTAL APORTACIONES.*?(\d[\d.,]*)",
        )

        irpf_porcentaje = self._parse_amount_optional(
            normalized,
            (
                r"(?:Retención a cta\.? IRPF|Ajuste IRPF paga extra)"
                r"\s+(\d[\d.,]*)\s*%"
            ),
        )

        irpf_importe = self._parse_amount_optional(
            normalized,
            (
                r"(?:Retención a cta\.? IRPF|Ajuste IRPF paga extra)"
                r"\s+\d[\d.,]*\s*%\s+(\d[\d.,]*)"
            ),
        )

        otras_deducciones = self._parse_amount_optional(
            normalized,
            r"^Donaciones\s+(\d[\d.,]*)$",
        )

        prorrata_pagas_extra = self._parse_amount_optional(
            normalized,
            r"Prorratas pagas extraordinarias.*?(\d[\d.,]*)",
        )

        base_ss_comunes = self._parse_amount_optional(
            normalized,
            r"Base de cotización normalizada.*?(\d[\d.,]*)",
        )

        base_irpf = self._parse_amount_optional(
            normalized,
            r"Base sujeta a retención del IRPF.*?(\d[\d.,]*)",
        )

        doc = Nomina(
            id=f"coritel-{anio:04d}-{mes:02d}-{tipo.value.lower()}",
            anio=anio,
            mes=mes,
            periodo=periodo,
            empresa=self.EMPRESA,
            cif=cif,
            tipo=tipo,
            categoria=categoria,
            grupo_cotizacion=grupo_cotizacion,
            salario_base=salario_base,
            plus_convenio=plus_convenio,
            complementos=complementos,
            prorrata_pagas_extra=prorrata_pagas_extra,
            total_devengado=total_devengado,
            descuento_seguridad_social=descuento_seguridad_social,
            irpf_porcentaje=irpf_porcentaje,
            irpf_importe=irpf_importe,
            otras_deducciones=otras_deducciones,
            total_deducir=total_deducir,
            liquido_percibir=liquido_percibir,
            base_ss_comunes=base_ss_comunes,
            base_irpf=base_irpf,
        )

        return self._validate(doc)

    @staticmethod
    def _normalize_text(text: str) -> str:
        lines = []

        for line in text.splitlines():
            # Coritel intercala puntos decorativos entre letras:
            # .T.O.T.A.L. .D.E.V.E.N.G.A.D.O
            cleaned = re.sub(
                r"\.(?=[A-Za-zÁÉÍÓÚáéíóúÑñ])",
                "",
                line,
            )

            # Elimina separadores visuales largos:
            # TOTAL DEVENGADO........................ 900,01
            #
            # Conserva puntos significativos de:
            # 03.04.2006
            # 1.065,13
            cleaned = re.sub(r"\.{2,}", " ", cleaned)

            # Elimina puntos decorativos aislados antes de espacio
            # o fin de línea.
            cleaned = re.sub(r"\.(?=\s|$)", " ", cleaned)

            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            lines.append(cleaned)

        return "\n".join(lines)

    @staticmethod
    def _parse_period(text: str) -> tuple[int, int, str]:
        match = re.search(
            r"PERIODO DE LIQUIDACIÓN:\s*"
            r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*"
            r"(\d{2})\.(\d{2})\.(\d{4})",
            text,
        )

        if not match:
            raise ValueError("Missing Coritel payroll period")

        (
            start_day,
            start_month,
            start_year,
            end_day,
            end_month,
            end_year,
        ) = match.groups()

        if start_month != end_month or start_year != end_year:
            raise ValueError(
                "Coritel payroll period spans multiple months"
            )

        periodo = (
            f"{start_day}.{start_month}.{start_year} - "
            f"{end_day}.{end_month}.{end_year}"
        )

        return int(end_year), int(end_month), periodo

    @staticmethod
    def _detect_document_type(text: str) -> TipoDocumento:
        if re.search(
            r"PERIODO DE LIQUIDACIÓN:.*?Total días:\s*0",
            text,
            re.IGNORECASE,
        ):
            return TipoDocumento.PAGA_EXTRA

        return TipoDocumento.NOMINA_ORDINARIA

    @staticmethod
    def _parse_required(
        text: str,
        pattern: str,
        error: str,
    ) -> str:
        match = re.search(
            pattern,
            text,
            re.MULTILINE | re.IGNORECASE,
        )

        if not match:
            raise ValueError(error)

        return match.group(1).strip()

    @staticmethod
    def _parse_optional(
        text: str,
        pattern: str,
    ) -> str | None:
        match = re.search(
            pattern,
            text,
            re.MULTILINE | re.IGNORECASE,
        )

        if not match:
            return None

        return match.group(1).strip()

    @classmethod
    def _parse_amount_required(
        cls,
        text: str,
        pattern: str,
        error: str,
    ) -> float:
        match = re.search(
            pattern,
            text,
            re.MULTILINE | re.IGNORECASE,
        )

        if not match:
            raise ValueError(error)

        return cls._to_float(match.group(1))

    @classmethod
    def _parse_amount_optional(
        cls,
        text: str,
        pattern: str,
    ) -> float:
        match = re.search(
            pattern,
            text,
            re.MULTILINE | re.IGNORECASE,
        )

        if not match:
            return 0.0

        return cls._to_float(match.group(1))

    @staticmethod
    def _to_float(value: str) -> float:
        cleaned = value.strip()

        if not re.fullmatch(
            r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?",
            cleaned,
        ):
            raise ValueError(
                f"Invalid monetary value: {value!r}"
            )

        return float(
            cleaned
            .replace(".", "")
            .replace(",", ".")
        )
