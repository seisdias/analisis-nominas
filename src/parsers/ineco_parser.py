"""INECO textual payrolls: explicit fundamentals, no inferred deductions."""

import calendar
import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from math import isfinite

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import ConceptoNomina, Nomina
from src.parsers.base import BaseParser


class InecoParser(BaseParser):
    _MONEY = re.compile(r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}")

    @staticmethod
    def _rows(text: str) -> list[str]:
        # Normalize spelling/spacing without ever joining separate rows.
        plain = "".join(c for c in unicodedata.normalize("NFD", text)
                        if not unicodedata.combining(c))
        return [" ".join(row.lower().split()) for row in plain.splitlines() if row.strip()]

    @classmethod
    def _amounts(cls, row: str, counts: tuple[int, ...], field: str) -> list[float]:
        tokens = row.split()
        if len(tokens) not in counts:
            raise ValueError(f"Missing or invalid INECO {field}")
        values = []
        for token in tokens:
            # Spanish thousands/decimals; a single leading OR trailing minus.
            negative = token.startswith("-") or token.endswith("-")
            unsigned = token[1:] if token.startswith("-") else token.removesuffix("-")
            if not cls._MONEY.fullmatch(unsigned):
                raise ValueError(f"Invalid INECO {field}")
            value = float(unsigned.replace(".", "").replace(",", "."))
            if not isfinite(value):
                raise ValueError(f"Non-finite INECO {field}")
            values.append(-value if negative else value)
        return values

    @staticmethod
    def _one_index(rows: list[str], pattern: str, field: str) -> int:
        indices = [i for i, row in enumerate(rows) if re.search(pattern, row)]
        if len(indices) != 1:
            raise ValueError(f"Missing or ambiguous INECO {field}")
        return indices[0]

    @classmethod
    def _period(cls, rows: list[str]) -> tuple[date, date]:
        index = cls._one_index(rows, r"^periodo (?:de )?liquidacion\b", "period")
        row = rows[index + 1] if index + 1 < len(rows) else ""
        match = re.match(r"^(\d{2}\.\d{2}\.\d{4}) (\d{2}\.\d{2}\.\d{4})(?: |$)", row)
        if not match:
            raise ValueError("Missing or invalid INECO payroll period")
        try:
            start, end = (datetime.strptime(value, "%d.%m.%Y").date()
                          for value in match.groups())
        except ValueError:
            raise ValueError("Invalid INECO payroll period") from None
        if start > end or (start.year, start.month) != (end.year, end.month):
            raise ValueError("Invalid INECO payroll period")
        return start, end

    @classmethod
    def _totals(cls, rows: list[str]) -> tuple[float, float, float, float | None, float | None]:
        old = [i for i, row in enumerate(rows)
               if row.endswith("base accidentes total devengos total deducciones")]
        modern = [i for i, row in enumerate(rows)
                  if row.endswith("base d irpf devengos deducciones")]
        if len(old) + len(modern) != 1:
            raise ValueError("Missing or ambiguous INECO payroll totals")
        base_irpf = None
        base_common = None
        if old:
            i = old[0] + 1
            if i < len(rows) and rows[i] == "remuneracion":
                i += 1
            amounts = cls._amounts(rows[i] if i < len(rows) else "", (4,), "totals")
            net_index = cls._one_index(rows, r"\bliquido a percibir:", "net total")
            base_row, net_row = rows[net_index].split("liquido a percibir:", 1)
            # The common base is the separate column alongside the net, not
            # the left-hand "Total Base" (which can differ in other layouts).
            labelled = any(re.search(r"\bb\.c\. ?comunes\b", row)
                           for row in rows[old[0] + 1:net_index])
            if labelled and base_row.strip():
                base_common = cls._amounts(base_row, (1,), "common SS base")[0]
            net = cls._amounts(net_row, (1,), "net total")[0]
        else:
            i = modern[0] + 1
            row = rows[i] if i < len(rows) else ""
            match = re.fullmatch(r"remu\. ?cotizables: (.+)", row)
            if not match:
                raise ValueError("Missing INECO payroll totals row")
            has_common_base = bool(re.search(r"\bb\.c\. ?comunes base d irpf", rows[modern[0]]))
            amounts = cls._amounts(match[1], (5 if has_common_base else 4,), "totals/base IRPF")
            base_irpf = amounts[-3]  # Printed Base D IRPF, not gross or SS base.
            base_common = amounts[1] if has_common_base else None
            i = cls._one_index(rows, r"\bliquido a percibir:?$", "net total") + 1
            row = rows[i] if i < len(rows) else ""
            prefix = "atra base cotiz:"
            if not row.startswith(prefix):
                raise ValueError("Missing INECO net total row")
            # Optional arrears base precedes the net column; never read the next bases row.
            net = cls._amounts(row[len(prefix):], (1, 2), "net total")[-1]
        return amounts[-2], amounts[-1], net, base_irpf, base_common

    @classmethod
    def _proration(cls, rows: list[str]) -> float | None:
        start = cls._one_index(rows, r"^cotizacion seg", "summary")
        end = cls._one_index(rows, r"\bliquido a percibir", "net total")
        rows = rows[start:end + 1]
        matches = [i for i, row in enumerate(rows)
                   if row.startswith("prorrata:")
                   or re.fullmatch(r"prorratas pagas(?: b\.c\. comunes)?", row)]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("Ambiguous INECO proration")
        i = matches[0]
        if rows[i].startswith("prorrata:"):
            value = rows[i].split(":", 1)[1].strip()
        else:
            value = rows[i + 1] if i + 1 < len(rows) else ""
            if value == "extras :":
                value = ""
        return cls._amounts(value, (1,), "proration")[0] if value else None

    @staticmethod
    def _irpf(concepts: list[ConceptoNomina]) -> tuple[float | None, float | None]:
        matches = [concept for concept in concepts if concept.codigo == "/401"]
        if not matches:
            return None, None
        if len(matches) != 1:
            raise ValueError("Ambiguous INECO IRPF row")
        return matches[0].porcentaje, matches[0].importe

    # Only labels observed in the supported tables. No filename/year/value rules.
    _CONCEPTS = {
        "9001": (r"salario base", "salario_base", (1,)),
        "9002": (r"plus convenio", "plus_convenio", (1,)),
        "9003": (r"antiguedad", "antiguedad", (1,)),
        "9004": (r"comp\. ?salarial", "complementos", (1,)),
        "9025": (r"pago de benefi(?:cios)?", "beneficios", (1,)),
        "9032": (r"paga extra(?: [a-z]+)?", "paga_extra_incluida", (1,)),
        "9033": (r"paga extra(?: [a-z]+)?", "paga_extra_incluida", (1,)),
        "90RG": (r"regulariz\.salar", "regularizaciones", (1,)),
        "9RPE": (r"r\. pext [a-z]+ \d{4}", "regularizaciones", (1,)),
        "PA40": (r"prestac\.oblig\.e", "prestaciones", (1, 2)),
        "PC10": (r"complementos it", "prestaciones", (1,)),
        "9102": (r"liquidacion vac", "vacaciones", (3,)),
        "90SV": (r"seguro de vida", "seguro_de_vida", (1,)),
        "9B09": (r"seguro de vida", "seguro_de_vida", (1,)),
        "T002": (r"dto base accidente", "cotizacion_trabajador", (1, 2)),
        "/350": (r"trab\.cont\.comunes", "cotizacion_trabajador", (1, 2)),
        "/401": (r"retencion irpf", "irpf", (2,)),
        "/402": (r"ingreso a cuenta irpf?", "ingreso_a_cuenta", (1,)),
    }

    @classmethod
    def _conceptos(cls, rows: list[str]) -> list[ConceptoNomina]:
        start = cls._one_index(rows, r"^conceptos? unidades precios? devengos deducciones$",
                               "concept table") + 1
        end = cls._one_index(rows, r"^cotizacion seg", "concept table end")
        if end <= start:
            raise ValueError("Invalid INECO concept table boundaries")
        concepts = []
        for row in rows[start:end]:
            code, _, rest = row.partition(" ")
            code = code.upper()
            definition = cls._CONCEPTS.get(code)
            # An explicitly labelled extra can have a different concept code.
            if definition is None and re.match(r"paga extra\b", rest):
                definition = (r"paga extra(?: [a-z]+)?", "paga_extra_incluida", (1,))
            if definition is None:
                raise ValueError("Unsupported INECO economic concept")
            pattern, category, counts = definition
            match = re.fullmatch(pattern + r"( ?atra\.)? (.+)", rest)
            if not match:
                raise ValueError("Invalid INECO concept label/amount")
            arrears = bool(match[1])
            raw_values = match[2]
            amount_text = raw_values.split()[-1]
            numeric_values = raw_values
            # Observed extraction variant ONLY in insurance cells. Never repair
            # grouped or malformed money elsewhere, or depend on a specific amount.
            if category == "seguro_de_vida" and re.fullmatch(r"\d+\.\d{2}-?", raw_values):
                numeric_values = raw_values.replace(".", ",")
            values = cls._amounts(numeric_values, counts, "IRPF" if code == "/401" else "concept amount")
            if arrears and category in {"salario_base", "plus_convenio", "complementos"}:
                category = "atrasos"
            deduction = category in {"cotizacion_trabajador", "irpf", "ingreso_a_cuenta"}
            percentage = values[0] if deduction and len(values) == 2 else None
            if percentage is not None and not 0 <= percentage <= 100:
                raise ValueError("Invalid INECO contribution percentage")
            concepts.append(ConceptoNomina(
                codigo=code, concepto=rest[:-len(raw_values)].strip(), categoria=category,
                columna="deducciones" if deduction else "devengos",
                importe=values[-1], importe_texto=amount_text, atraso=arrears,
                porcentaje=percentage,
                unidades=values[0] if category in {"prestaciones", "vacaciones"} and len(values) > 1 else None,
                precio=values[1] if category == "vacaciones" else None,
            ))
        cls._insurance_columns(concepts)
        return concepts

    @staticmethod
    def _insurance_columns(concepts: list[ConceptoNomina]) -> None:
        # Both supported templates list the earnings block before the employee
        # deductions block. Flattened text loses x coordinates. Insurance entries
        # straddle these blocks: require mirrored amounts rather than guessing an
        # unpaired cell's column. Ambiguous future layouts must be reviewed.
        insurance = [c for c in concepts if c.categoria == "seguro_de_vida"]
        if not insurance:
            return
        ordinary = [i for i, c in enumerate(concepts)
                    if c.columna == "devengos" and c.categoria != "seguro_de_vida"]
        deductions = [i for i, c in enumerate(concepts) if c.columna == "deducciones"]
        if not ordinary or not deductions or max(ordinary) >= min(deductions):
            raise ValueError("Ambiguous INECO insurance columns")
        boundary = max(ordinary)
        for i, concept in enumerate(concepts):
            if concept.categoria == "seguro_de_vida" and i > boundary:
                concept.columna = "deducciones"
        earnings = Counter((c.codigo, c.importe) for c in insurance if c.columna == "devengos")
        deductions_insurance = Counter((c.codigo, c.importe) for c in insurance if c.columna == "deducciones")
        if not earnings or earnings != deductions_insurance:
            raise ValueError("Ambiguous INECO insurance columns: unmatched printed entries")

    @staticmethod
    def _ordinary_total(concepts: list[ConceptoNomina], code: str) -> float:
        # Compatibility aggregates exclude ATRA rows, retained separately above.
        return round(sum(c.importe for c in concepts if c.codigo == code and not c.atraso), 2)

    def parse(self, text: str, filename: str = "") -> Nomina:
        rows = self._rows(text)
        start, end = self._period(rows)
        if not any(re.search(r"\bing\.y econ\.del transporte\b.*\ba28220168\b", row)
                   for row in rows):
            raise ValueError("Missing or invalid INECO company identity/CIF")
        if any(re.search(r"\bfiniquito\b", row) for row in rows):
            raise ValueError("Settlement documents are not supported by INECO payroll parsing")
        gross, deductions, net, base_irpf, base_common = self._totals(rows)
        concepts = self._conceptos(rows)
        rate, tax = self._irpf(concepts)
        period = f"{start.year:04d}-{start.month:02d}"
        # Preserve legacy storage keys for full months, including the historical EXTRA
        # suffix. An included extra is NOT a standalone extra payroll classification.
        legacy_suffix = "-EXTRA" if "PAGA EXTRA" in text.upper() else ""
        doc_id = f"{period}-INECO{legacy_suffix}"
        if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]:
            # Old monthly IDs are ambiguous for split payrolls: they cannot safely be
            # migrated automatically without examining the existing stored document.
            doc_id = f"{period}-INECO-{start.isoformat()}_{end.isoformat()}"
        return self._validate(Nomina(
            id=doc_id, anio=start.year, mes=start.month, periodo=period,
            fecha_inicio=start.isoformat(), fecha_fin=end.isoformat(),
            empresa="Ing.y Econ.del Transporte", cif="A28220168",
            tipo=TipoDocumento.NOMINA_ORDINARIA,
            total_devengado=gross, total_deducir=deductions, liquido_percibir=net,
            irpf_porcentaje=rate, irpf_importe=tax, base_irpf=base_irpf,
            descuento_seguridad_social=None, otras_deducciones=None,
            base_ss_comunes=base_common, prorrata_pagas_extra=self._proration(rows),
            conceptos=concepts,
            salario_base=self._ordinary_total(concepts, "9001"),
            plus_convenio=self._ordinary_total(concepts, "9002"),
            complementos=self._ordinary_total(concepts, "9004"),
            observaciones=f"Procesado desde {filename}",
        ))
