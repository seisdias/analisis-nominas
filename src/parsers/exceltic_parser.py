"""Exceltic's textual payroll table, with printed values and bounded sections."""

import calendar
import re
import unicodedata
from collections import Counter
from datetime import date
from math import isfinite

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import ConceptoNomina, Nomina
from src.parsers.base import BaseParser


class ExcelticParser(BaseParser):
    _MONEY = r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}"
    _LABELS = {
        "SALARIO BASE": "salario_base",
        "PLUS CONVENIO": "plus_convenio",
        "P.P.EXTRA": "paga_extra_incluida",
        "MEJORA VOLUNTARIA": "complemento_salarial",
        "AYUDA COMIDA": "ayuda_comida",
        "AYUDA GUARDERIA": "ayuda_guarderia",
        "DTO. CONT. COMUNES": "cotizacion_contingencias_comunes",
        "DTO.BASE ACCIDENTE": "cotizacion_desempleo_formacion_profesional",
        "RETENCION IRPF": "irpf",
    }

    @staticmethod
    def _rows(text: str) -> list[str]:
        plain = "".join(c for c in unicodedata.normalize("NFD", text)
                        if not unicodedata.combining(c))
        return [" ".join(line.upper().split()) for line in plain.splitlines() if line.strip()]

    @classmethod
    def _number(cls, value: str, field: str, decimals: int = 2) -> float:
        pattern = cls._MONEY if decimals == 2 else r"\d+,\d{4}"
        if not re.fullmatch(pattern, value):
            raise ValueError(f"Invalid Exceltic {field}")
        amount = float(value.replace(".", "").replace(",", "."))
        if not isfinite(amount):
            raise ValueError(f"Non-finite Exceltic {field}")
        return amount

    @staticmethod
    def _index(rows: list[str], pattern: str, field: str) -> int:
        indices = [i for i, row in enumerate(rows) if re.fullmatch(pattern, row)]
        if len(indices) != 1:
            raise ValueError(f"Missing or ambiguous Exceltic {field}")
        return indices[0]

    @classmethod
    def _period(cls, rows: list[str]) -> tuple[date, date]:
        i = cls._index(rows, r"DEL .*", "payroll period")
        match = re.fullmatch(
            r"DEL (\d{2}) DE (\d{2}) AL (\d{2}) DE (\d{2}) DE (\d{4})"
            r"(?: \d{2}-\d{2}-\d{4} \d+)?", rows[i],
        )
        if not match:
            raise ValueError("Invalid Exceltic payroll period")
        d1, m1, d2, m2, year = map(int, match.groups())
        try:
            start, end = date(year, m1, d1), date(year, m2, d2)
        except ValueError:
            raise ValueError("Invalid Exceltic payroll period") from None
        if start > end or start.month != end.month:
            raise ValueError("Invalid Exceltic payroll period")
        return start, end

    @classmethod
    def _concepts(cls, rows: list[str]) -> list[ConceptoNomina]:
        result = []
        for row in rows:
            if row == "PAGO POR TRANSFERENCIA":
                continue
            match = re.fullmatch(
                r"(?:(\S+) (\S+) )?([12]) (.+?) (\S+%)? ?(\S+)", row,
            )
            if not match:
                raise ValueError("Invalid Exceltic concept row")
            units, price, flag, label, rate, amount = match.groups()
            category = cls._LABELS.get(label)
            if category is None:
                raise ValueError("Unsupported Exceltic concept")
            # 1/2 are NOT unique concept codes or universal column markers.
            # In this audited template, known earnings carry 1, deductions 2.
            # Only the two mirrored aid labels appear on both sides.
            aid = category in {"ayuda_comida", "ayuda_guarderia"}
            deduction = category.startswith("cotizacion_") or category == "irpf"
            if not aid and flag != ("2" if deduction else "1"):
                raise ValueError("Ambiguous Exceltic concept column")
            percentage = cls._number(rate[:-1], "percentage") if rate else None
            if percentage is not None and not 0 <= percentage <= 100:
                raise ValueError("Invalid Exceltic percentage")
            result.append(ConceptoNomina(
                codigo=flag, concepto=label, categoria=category,
                columna="deducciones" if flag == "2" else "devengos",
                importe=cls._number(amount, "concept amount"), importe_texto=amount,
                unidades=cls._number(units, "units") if units else None,
                precio=cls._number(price, "price", decimals=4) if price else None,
                porcentaje=percentage,
            ))
        for category in ("ayuda_comida", "ayuda_guarderia"):
            aid_rows = [c for c in result if c.categoria == category]
            earned = Counter(c.importe for c in aid_rows if c.columna == "devengos")
            deducted = Counter(c.importe for c in aid_rows if c.columna == "deducciones")
            if earned != deducted:
                raise ValueError("Ambiguous Exceltic mirrored aid columns")
        return result

    @classmethod
    def _label_amount(cls, rows: list[str], label: str) -> float | None:
        matches = [row[len(label):].strip() for row in rows
                   if row == label or row.startswith(label + " ")]
        if len(matches) > 1:
            raise ValueError("Ambiguous Exceltic " + label)
        return cls._number(matches[0], label) if matches and matches[0] else None

    @staticmethod
    def _category_total(concepts: list[ConceptoNomina], category: str) -> float:
        # Compatibility aggregates of explicit entries, never inferred remainders.
        return round(sum(c.importe for c in concepts if c.categoria == category), 2)

    def parse(self, text: str, filename: str = "") -> Nomina:
        rows = self._rows(text)
        start, end = self._period(rows)
        if (not any(re.search(r"\bEXCELTIC SL\b", row) for row in rows)
                or not any(re.search(r"\bB84242767\b", row) for row in rows)):
            raise ValueError("Missing or invalid Exceltic company identity/CIF")
        if any(re.search(r"\b(FINIQUITO|CERTIFICADO)\b", row) for row in rows):
            raise ValueError("Unsupported Exceltic document type")
        table = self._index(rows, r"CONCEPTO", "concept table") + 1
        summary = self._index(
            rows, r"DETERMINACION DE LAS BASES DE COTIZACION .* TOTAL DEVENGO TOTAL DEDU\.",
            "totals header",
        )
        footer = self._index(rows, r"CONCEPTO BASE TIPO APORTACION EMPRESA", "bases table")
        if not table < summary < footer:
            raise ValueError("Invalid Exceltic section order")
        concepts = self._concepts(rows[table:summary])
        block = rows[summary + 1:footer]
        i = self._index(
            block, r"BASE TOTAL DE COTIZACION DESG\.BASES GRU IMPORTE % APOR\.TRAB\. .*",
            "totals",
        )
        tokens = block[i].split("APOR.TRAB. ", 1)[1].split()
        if len(tokens) != 2:
            raise ValueError("Invalid Exceltic totals")
        gross, deductions = (self._number(value, "totals") for value in tokens)
        money = self._MONEY
        i = self._index(block, r"REMUN\.TOTAL .* LIQUIDO TOTAL A PERCIBIR", "net header")
        common = re.fullmatch(
            rf"REMUN\.TOTAL {money} REG\.GRAL\. \d+ (?:(?P<base>{money}) )?"
            rf"(?P<rate>{money}) (?P<amount>{money}) LIQUIDO TOTAL A PERCIBIR", block[i],
        )
        if not common or i + 2 >= len(block):
            raise ValueError("Invalid Exceltic common base/net section")
        fp = re.fullmatch(
            rf"PROR\.PAG\.EX\. (?:(?P<proration>{money}) )?"
            rf"DESEMPLEO-F\.P\. (?P<base>{money}) (?P<rate>{money}) (?P<amount>{money})",
            block[i + 1],
        )
        if not fp:
            raise ValueError("Invalid Exceltic proration/contribution row")
        net = self._number(block[i + 2], "net total")
        for category, match in (
            ("cotizacion_contingencias_comunes", common),
            ("cotizacion_desempleo_formacion_profesional", fp),
        ):
            found = [c for c in concepts if c.categoria == category]
            if (len(found) != 1 or found[0].importe != self._number(match["amount"], "contribution")
                    or found[0].porcentaje != self._number(match["rate"], "contribution rate")):
                raise ValueError("Inconsistent Exceltic contribution summary")
        # Explicit summary evidence is checked, not appended as new economic entries.
        proration = self._number(fp["proration"], "proration") if fp["proration"] else None
        bottom = rows[footer + 1:]
        bottom_proration = self._label_amount(bottom, "IMPORTE PRORRATA PAGAS EXTRAORDINARIAS")
        if proration is not None and bottom_proration is not None and proration != bottom_proration:
            raise ValueError("Inconsistent Exceltic proration")
        if proration is None:
            proration = bottom_proration
        base_at_ep = None
        at_rows = [row for row in bottom if row == "AT Y EP" or row.startswith("AT Y EP ")]
        if len(at_rows) > 1:
            raise ValueError("Ambiguous Exceltic AT/EP base")
        if at_rows:
            values = at_rows[0][len("AT Y EP"):].split()
            if values:
                if len(values) != 3:
                    raise ValueError("Invalid Exceltic AT/EP row")
                base_at_ep = self._number(values[0], "AT/EP base")
                for value in values[1:]:
                    self._number(value, "employer contribution")
        taxes = [c for c in concepts if c.categoria == "irpf"]
        if len(taxes) > 1:
            raise ValueError("Ambiguous Exceltic IRPF")
        period = f"{start.year:04d}-{start.month:02d}"
        doc_id = f"{period}-EXCELTIC"
        # Preserve full-month legacy IDs; partial periods need explicit boundaries.
        if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]:
            doc_id += f"-{start.isoformat()}_{end.isoformat()}"
        return self._validate(Nomina(
            id=doc_id, anio=start.year, mes=start.month, periodo=period,
            empresa="EXCELTIC SL", cif="B84242767", tipo=TipoDocumento.NOMINA_ORDINARIA,
            fecha_inicio=start.isoformat(), fecha_fin=end.isoformat(),
            total_devengado=gross, total_deducir=deductions, liquido_percibir=net,
            irpf_porcentaje=taxes[0].porcentaje if taxes else None,
            irpf_importe=taxes[0].importe if taxes else None,
            base_irpf=self._label_amount(bottom, "BASE SUJETA A RETENCION DEL IRPF"),
            base_ss_comunes=self._number(common["base"], "common base") if common["base"] else None,
            base_at_ep=base_at_ep, prorrata_pagas_extra=proration,
            salario_base=self._category_total(concepts, "salario_base"),
            plus_convenio=self._category_total(concepts, "plus_convenio"),
            complementos=self._category_total(concepts, "complemento_salarial"),
            descuento_seguridad_social=None, otras_deducciones=None, conceptos=concepts,
        ))
