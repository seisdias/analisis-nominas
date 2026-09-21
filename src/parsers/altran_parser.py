"""Altran monthly payrolls: printed fundamentals and positional concept cells."""
import calendar
import re
from datetime import date
from typing import Literal

from src.extraction import ExtractedDocument, ExtractedWord
from src.models.nomina import ConceptoNomina, Nomina
from src.parsers.base import BaseParser

_MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


# Categories describe printed labels, never the economic column.
_CATEGORIES = {
    'Salario Base': 'salario_base',
    'Plus Convenio': 'plus_convenio',
    'Parte Proporcional Pagas Extras': 'paga_extra_incluida',
    'Mejora Voluntaria': 'mejora_voluntaria',
    'Valor Seguro Salud': 'seguro_salud',
    'Ret.Esp.Seg.Vida / Accidente': 'seguro_vida_accidente',
    'Dto.Ret.Esp.Seg.Vida / Accidente': 'seguro_vida_accidente',
    'Dto. Seguro Salud': 'seguro_salud',
    'Cotización Desempleo y FP': 'cotizacion_desempleo_fp',
    'Cotización Contingencias Comunes': 'cotizacion_contingencias_comunes',
    'Retención I.R.P.F. Especie': 'irpf_especie',
    'Retención I.R.P.F.': 'irpf_ordinario',
    'Compensa Comida': 'compensacion_comida',
    'Compensa Guardería': 'compensacion_guarderia',
    'Ayuda ADSL': 'ayuda_adsl',
    'Compensación Jornada Intensiva': 'compensacion_jornada_intensiva',
    'Cotización Ticket Jornada Intensiva': 'ticket_jornada_intensiva',
    'Dto. Ticket Jornada Intensiva': 'ticket_jornada_intensiva',
    'Compensa Salud': 'compensacion_salud',
    'Prestación 12 Días Siguientes Empresa': 'prestacion_it_empresa',
    'Complemento IT/AT/MAT': 'complemento_it_at_mat',
    'Compensa Transporte': 'compensacion_transporte',
    'Actuaciones': 'actuaciones',
    'Antigüedad': 'antiguedad',
    'Prestación Enfermedad': 'prestacion_it',
    'Comida Devolución Saldo': 'devolucion_saldo_comida',
    'Compensación Cesta Navidad': 'compensacion_cesta_navidad',
    'Disponibilidad': 'disponibilidad',
    'Transporte Devolución Saldo': 'devolucion_saldo_transporte',
    'Horas Extras': 'horas_extra',
    'COTIZACION HORAS EXTRAS NORMALES': 'cotizacion_horas_extra',
    'Gratificación Extraordinaria': 'gratificacion_extraordinaria',
    'Ayuda Teletrabajo': 'ayuda_teletrabajo',
}
_TAX_CATEGORIES = {
    "irpf_ordinario", "irpf_especie", "cotizacion_desempleo_fp",
    "cotizacion_contingencias_comunes", "cotizacion_horas_extra",
}
_UNIT_CATEGORIES = {"salario_base", "plus_convenio", "mejora_voluntaria", "antiguedad"}

def _number(value: str) -> float:
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2,4}", value):
        raise ValueError("Invalid printed Altran amount")
    return float(value.replace(".", "").replace(",", "."))


def _one(values: list[str], field: str) -> str:
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous Altran {field}")
    return values[0]


class AltranParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        periods = re.findall(
            r"\bDel\s*(\d{1,2})\s*al\s*(\d{1,2})\s*de\s*([A-Za-z]+)\s+(\d{4})(?!\d)",
            text, re.I,
        )
        if len(periods) != 1:
            raise ValueError("Missing or ambiguous Altran period")
        first, last, month_name, year = periods[0]
        try:
            month = _MONTHS.index(month_name.lower()) + 1
            start, end = date(int(year), month, int(first)), date(int(year), month, int(last))
        except ValueError as exc:
            raise ValueError("Invalid Altran period") from exc
        if start > end:
            raise ValueError("Invalid Altran period")
        period = start.strftime("%Y-%m")
        identifier = f"{period}-ALTRAN"
        if start.day != 1 or end.day != calendar.monthrange(start.year, start.month)[1]:
            identifier += f"-{start.isoformat()}_{end.isoformat()}"

        company = _one([m[1] for line in lines if (m := re.match(
            r"^(ALTRAN INNOVACION S\.L\.)(?=\s+Señor|$)", line, re.I,
        ))], "company")
        cifs = [m[1] for line in lines if (m := re.fullmatch(r"CIF:\s*(\w+)", line, re.I))]
        if cifs != ["B80428972"]:
            raise ValueError("Invalid Altran CIF")

        header = _one([line for line in lines if line ==
                       "Periodo Código Concepto Cantidad/Base Precio/% Devengos Deducciones"],
                      "concept table")
        totals = _one([line for line in lines if line.startswith("Seguridad Social Totales")],
                      "totals")
        begin, finish = lines.index(header), lines.index(totals)
        if begin >= finish:
            raise ValueError("Invalid Altran table boundaries")
        rows = lines[begin + 1:finish]
        match = re.fullmatch(r"Seguridad Social Totales (\S+) (\S+)", totals)
        if match is None:
            raise ValueError("Invalid Altran totals")
        gross, deductions = _number(match[1]), _number(match[2])

        footer = lines[finish + 1:]
        for i, line in enumerate(footer):
            if line in ("Cotización Empresa", "Acumulados"):
                footer = footer[:i]
                break
        net_line = _one([line for line in footer if "líquido a percibir" in line.lower()],
                        "net total")
        net = _number(re.sub(r"^.*?Líquido a percibir\s*", "", net_line, flags=re.I))
        common, accident, proration = self._bases(footer)

        row_period = f"{start.month:02d}/{start.year % 100:02d}"
        tax = self._row(rows, "F74", "Retención I.R.P.F.", row_period, required=False)
        # These existing scalar fields cannot express None. Read their ordinary
        # printed rows or reject explicitly; do not fill them with zero/residuals.
        salary = self._row(rows, "R1A", "Salario Base", row_period, required=True)
        agreement = self._row(rows, "R1B", "Plus Convenio", row_period, required=True)
        improvement = self._row(rows, "R1R", "Mejora Voluntaria", row_period, required=True)
        assert salary is not None and agreement is not None and improvement is not None
        return self._validate(Nomina(
            id=identifier, anio=start.year, mes=start.month, periodo=period,
            empresa=company.upper(), cif=cifs[0],
            fecha_inicio=start.isoformat(), fecha_fin=end.isoformat(),
            total_devengado=gross, total_deducir=deductions, liquido_percibir=net,
            base_irpf=tax[0] if tax else None,
            irpf_porcentaje=tax[1] if tax else None,
            irpf_importe=tax[2] if tax else None,
            base_ss_comunes=common, base_at_ep=accident, prorrata_pagas_extra=proration,
            descuento_seguridad_social=None, otras_deducciones=None,
            salario_base=salary[2], plus_convenio=agreement[2], complementos=improvement[2],
        ))


    def parse_extracted(self, document: ExtractedDocument, filename: str = "") -> Nomina:
        payroll = self.parse(document.text, filename=filename)
        if not document.words:
            raise ValueError("Altran concept extraction requires layout")
        headings = ("Periodo", "Código", "Concepto", "Cantidad/Base",
                    "Precio/%", "Devengos", "Deducciones")
        tables = []
        for anchor in document.words:
            if anchor.text != "Devengos":
                continue
            tolerance = (anchor.bottom - anchor.top) / 2
            same_row = [w for w in document.words if w.page == anchor.page
                        and abs(w.top - anchor.top) <= tolerance]
            cells = [[w for w in same_row if w.text == label] for label in headings]
            if all(len(cell) == 1 for cell in cells):
                tables.append([cell[0] for cell in cells])
        if len(tables) != 1:
            raise ValueError("Missing or ambiguous Altran concept layout headings")
        header = tables[0]
        if any(a.x1 >= b.x0 for a, b in zip(header, header[1:])):
            raise ValueError("Overlapping Altran concept headings")
        page_words = [w for w in document.words if w.page == header[0].page]
        start = max(w.bottom for w in header)
        endings = [w.top for w in page_words if w.text == "Totales" and w.top > start]
        if not endings:
            raise ValueError("Missing Altran concept layout boundary")
        end = min(endings)
        body = sorted((w for w in page_words if start < w.top and w.bottom < end),
                      key=lambda w: (w.top, w.x0))
        rows: list[list[ExtractedWord]] = []
        for word in body:
            if rows and abs(word.top - rows[-1][0].top) <= (
                rows[-1][0].bottom - rows[-1][0].top
            ) / 2:
                rows[-1].append(word)
            else:
                rows.append([word])
        rows = [sorted(row, key=lambda w: w.x0) for row in rows]
        lines = [" ".join(line.split()) for line in document.text.splitlines() if line.strip()]
        text_start = lines.index(" ".join(headings)) + 1
        text_end = next(i for i, line in enumerate(lines)
                        if line.startswith("Seguridad Social Totales"))
        if [" ".join(w.text for w in row) for row in rows] != lines[text_start:text_end]:
            raise ValueError("Altran text/layout concept rows disagree")
        period = f"{payroll.mes:02d}/{payroll.anio % 100:02d}"
        concepts = []
        for row in rows:
            if len(row) < 4 or row[0].text not in (period, "ATR."):
                raise ValueError("Invalid Altran concept row period")
            code = row[1].text
            if not re.fullmatch(r"[A-Z0-9]{3}", code):
                raise ValueError("Invalid Altran concept code")
            if not (header[0].x0 <= row[0].x0 < row[0].x1 < header[1].x0
                    and header[1].x0 <= row[1].x0 < row[1].x1 < header[2].x0):
                raise ValueError("Ambiguous Altran concept identity cells")
            quantity_start = header[3].x0
            price_start = (header[3].x1 + header[4].x0) / 2
            amount_start = (header[4].x1 + header[5].x0) / 2
            descriptions, quantities, prices, amounts = [], [], [], []
            for word in row[2:]:
                if header[2].x0 <= word.x0 < word.x1 <= quantity_start:
                    descriptions.append(word.text)
                elif quantity_start <= word.x0 < word.x1 <= price_start:
                    quantities.append(word.text)
                elif price_start <= word.x0 < word.x1 <= amount_start:
                    prices.append(word.text)
                elif word.x0 >= amount_start:
                    amounts.append(word)
                else:
                    raise ValueError("Altran word crosses concept cell boundaries")
            if not descriptions or len(quantities) > 1 or len(prices) > 1 or len(amounts) != 1:
                raise ValueError("Missing or ambiguous Altran concept cells")
            description = " ".join(descriptions)
            category = _CATEGORIES.get(description, "otro")
            quantity = self._concept_number(quantities[0]) if quantities else None
            price = self._concept_number(prices[0]) if prices else None
            if (quantity is not None or price is not None) and category not in (
                _TAX_CATEGORIES | _UNIT_CATEGORIES
            ):
                raise ValueError("Unknown Altran quantity/base cell semantics")
            tax = category in _TAX_CATEGORIES
            amount = amounts[0]
            concepts.append(ConceptoNomina(
                codigo=code, concepto=description, categoria=category,
                columna=self.concept_column(document, amount),
                importe=self._concept_number(amount.text), importe_texto=amount.text,
                atraso=row[0].text == "ATR.",
                base=quantity if tax else None, porcentaje=price if tax else None,
                unidades=None if tax else quantity, precio=None if tax else price,
            ))
        ordinary_tax = [c for c in concepts if c.codigo == "F74" and not c.atraso]
        if ordinary_tax:
            if len(ordinary_tax) != 1:
                raise ValueError("Ambiguous ordinary Altran F74 concepts")
            tax_row = ordinary_tax[0]
            if (tax_row.columna != "deducciones"
                    or (tax_row.base, tax_row.porcentaje, tax_row.importe) != (
                        payroll.base_irpf, payroll.irpf_porcentaje, payroll.irpf_importe)):
                raise ValueError("Altran F74 layout disagrees with printed scalar fields")
        payroll.conceptos = concepts
        return payroll

    @staticmethod
    def _concept_number(value: str) -> float:
        negative = value.startswith("-") or value.endswith("-")
        unsigned = value[1:] if value.startswith("-") else value.removesuffix("-")
        number = _number(unsigned)
        return -number if negative else number

    @staticmethod
    def _row(
        rows: list[str], code: str, description: str, period: str, *, required: bool,
    ) -> tuple[float, float, float] | None:
        # ATR. rows are deliberately outside these ordinary scalar fields.
        candidates = [line for line in rows
                      if re.match(rf"^\d{{2}}/\d{{2}} {re.escape(code)}\b", line)]
        if not candidates and not required:
            return None
        line = _one(candidates, code)
        match = re.fullmatch(
            rf"{re.escape(period)} {re.escape(code)} {re.escape(description)} (\S+) (\S+) (\S+)",
            line,
        )
        if match is None:
            raise ValueError(f"Invalid Altran {code} row")
        return _number(match[1]), _number(match[2]), _number(match[3])

    @staticmethod
    def _bases(footer: list[str]) -> tuple[float | None, float | None, float | None]:
        heading = _one([line for line in footer if re.fullmatch(
            r"Comunes de Trabajo Pagas Extras (?:Normales F\.Mayor|Ordina\. Compl\.)", line,
        )], "SS base headings")
        if not any(re.match(r"Conti(?:n)?gencias Accidente Prorrata Horas\b", line)
                   for line in footer):
            raise ValueError("Missing Altran SS base context")
        index = footer.index(heading) + 1
        if index == len(footer) or footer[index].startswith("Sello y firma:"):
            return None, None, None
        values = footer[index].removesuffix(" Sello y firma:").split()
        # Two values after extraction cannot locate the empty cell safely.
        if len(values) != 3:
            raise ValueError("Ambiguous Altran SS base cells")
        return _number(values[0]), _number(values[1]), _number(values[2])

    @staticmethod
    def concept_column(
        document: ExtractedDocument, amount: ExtractedWord,
    ) -> Literal["devengos", "deducciones"]:
        """Locate one amount within the Altran table, without interpreting it.

        Regions follow the Precio/%, Devengos and Deducciones headings.
        Words crossing a boundary, missing layout or non-table words fail
        explicitly. This helper never interprets the amount or its code.
        """
        if not document.words:
            raise ValueError("Altran column classification requires layout")
        if amount not in document.words:
            raise ValueError("Amount is not part of the extracted document")
        words = [w for w in document.words if w.page == amount.page]
        regions = []
        for dev in (w for w in words if w.text.casefold() == "devengos"):
            # Header words share a baseline; tolerance scales with font height.
            tolerance = (dev.bottom - dev.top) / 2
            row = [w for w in words if abs(w.top - dev.top) <= tolerance]
            prices = [w for w in row if w.text.casefold() == "precio/%"]
            deductions = [w for w in row if w.text.casefold() == "deducciones"]
            if len(prices) != 1 or len(deductions) != 1:
                continue
            price, deduction = prices[0], deductions[0]
            if not price.x1 < dev.x0 < dev.x1 < deduction.x0:
                continue
            totals = [w for w in words if w.text.casefold() == "totales"
                      and w.top > dev.bottom]
            if not totals:
                continue
            end = min(w.top for w in totals)
            if not dev.bottom < amount.top or not amount.bottom < end:
                continue
            left = (price.x1 + dev.x0) / 2
            middle = (dev.x1 + deduction.x0) / 2
            right = deduction.x1 + (deduction.x0 - dev.x1) / 2
            regions.append((left, middle, right))
        if len(regions) != 1:
            raise ValueError("Missing or ambiguous Altran column headings")
        left, middle, right = regions[0]
        if left <= amount.x0 < amount.x1 <= middle:
            return "devengos"
        if middle <= amount.x0 < amount.x1 <= right:
            return "deducciones"
        raise ValueError("Altran amount outside or across economic columns")
