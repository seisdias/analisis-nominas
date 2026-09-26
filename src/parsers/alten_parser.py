"""ALTEN page-level documentary parsing; no PDF I/O or version selection."""

import calendar
import re
from dataclasses import replace
from datetime import date, datetime
from math import isfinite

from src.extraction import ExtractedDocument, ExtractedWord
from src.models.nomina import ConceptoNomina, Nomina
from src.parsers.base import BaseParser

_MONEY = re.compile(r"-?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}")
_COMPANIES = ("ALTEN S.P.A.IN. S.A.", "ALTEN DELIVERY CENTER SPAIN SLU")
_CATEGORIES = {
    "Salario Base Convenio": "salario_base",
    "Plus Convenio": "plus_convenio",
    "A Cuenta Convenio": "complemento_salarial",
    "P.P. Extra Verano": "paga_extra_incluida",
    "P.P. Extra Navidad": "paga_extra_incluida",
    "Bono/Variable": "variable",
    "Bono": "bono",
    "Antigüedad": "antiguedad",
    "Prestac.oblig.Empresa-E": "prestacion_it_empresa",
    "Prestaciones IT": "prestacion_it",
    "Complementos IT": "complemento_it",
    "Trab.cont.comunes": "cotizacion_contingencias_comunes",
    "Trab.desempleo": "cotizacion_desempleo",
    "Trab.formac.profesional": "cotizacion_formacion",
    "Retención a cta. IRPF": "irpf",
    "Trab. cuota solidaridad": "cotizacion_solidaridad",
}
_FOOTER = (
    ("REM.TOTAL", "rem_total"),
    ("PRORRATA", "prorrata_pagas_extra"),
    ("PROR.OTROS", "pror_otros"),
    ("BASES.S.", "base_ss_comunes"),
    ("BASEA.T./E.P.", "base_at_ep"),
    ("BASEIRPF", "base_irpf_pie"),
    ("BASEIRPFEsp", "base_irpf_especie"),
)


def _compact(text: str) -> str:
    return "".join(text.split())


def _numbers(text: str) -> list[tuple[str, float, int, int]]:
    """Consume an entire printed numeric region, never match numeric substrings."""
    value = _compact(text)
    result = []
    pos = 0
    while pos < len(value):
        match = _MONEY.match(value, pos)
        if match is None:
            raise ValueError("Invalid ALTEN printed number/cell")
        raw = match[0]
        number = float(raw.replace(".", "").replace(",", "."))
        if not isfinite(number):
            raise ValueError("Non-finite ALTEN printed number")
        result.append((raw, number, match.start(), match.end()))
        pos = match.end()
    return result


def _one(values: list[str], label: str) -> str:
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous ALTEN {label}; provide one payroll page")
    return values[0]


def _iso(value: str) -> str:
    return datetime.strptime(value, "%d.%m.%Y").date().isoformat()


def _row(chars: tuple[ExtractedWord, ...], top: float, tolerance: float) -> list[ExtractedWord]:
    return [c for c in chars if abs(c.top - top) <= tolerance]


def _cells(chars: list[ExtractedWord]) -> list[tuple[str, float, float, float]]:
    visible = sorted((c for c in chars if not c.text.isspace()), key=lambda c: c.x0)
    if any(len(c.text) != 1 for c in visible):
        raise ValueError("ALTEN requires character-level positional evidence")
    return [
        (raw, number, min(c.x0 for c in visible[a:b]), max(c.x1 for c in visible[a:b]))
        for raw, number, a, b in _numbers("".join(c.text for c in visible))
    ]


class AltenParser(BaseParser):
    @staticmethod
    def template(text: str) -> str:
        plain = _compact(text)
        if _compact(_COMPANIES[0]) in plain:
            return "N1a"
        if _compact(_COMPANIES[1]) in plain:
            return "N2" if "Categoríaconvenio" in plain else "N1b"
        raise ValueError("Invalid ALTEN company")

    @staticmethod
    def period_key(payroll: Nomina) -> str:
        return f"{payroll.cif}|{payroll.fecha_inicio}|{payroll.fecha_fin}|{payroll.tipo.value}"

    def parse_pages(self, document: ExtractedDocument, filename: str = "") -> list[Nomina]:
        """Preserve physical page order and every version. Unsupported pages fail."""
        pages = document.pages if document.pages is not None else (document,)
        return [self.parse_extracted(page, filename) for page in pages]

    def parse(self, text: str, filename: str = "") -> Nomina:
        """Text-only compatibility: printed fundamentals, without guessing layout cells."""
        lines = [_compact(line) for line in text.splitlines() if line.strip()]
        period = _one(
            re.findall(
                r"Periododeliquidacióndel(\d{2}\.\d{2}\.\d{4}al\d{2}\.\d{2}\.\d{4})",
                "\n".join(lines),
            ),
            "payroll period",
        )
        first, last = period.split("al")
        start, end = date.fromisoformat(_iso(first)), date.fromisoformat(_iso(last))
        if start > end:
            raise ValueError("Invalid ALTEN payroll period")
        company = _one(
            [name for name in _COMPANIES if any(line.startswith(_compact(name)) for line in lines)],
            "company",
        )
        if not re.search(r"(?<![\dA-Za-z])B\s*0\s*5\s*3\s*6\s*6\s*1\s*1\s*7(?![\dA-Za-z])", text):
            raise ValueError("Missing or invalid ALTEN CIF")
        header = _one(
            [line for line in lines if line == "CLAVEDESCRIPCIÓNUNIDADPRECIODEVENGOSDEDUCCIONES"],
            "concept table",
        )
        net_line = _one(
            [line for line in lines if line.startswith("LIQUIDOAPERCIBIR")], "net total"
        )
        ni = lines.index(net_line)
        if ni <= lines.index(header) + 1:
            raise ValueError("Missing ALTEN payroll totals")
        totals = _numbers(lines[ni - 1])
        net = _numbers(net_line.removeprefix("LIQUIDOAPERCIBIR"))
        if len(totals) != 2 or len(net) != 1:
            raise ValueError("Missing or ambiguous ALTEN payroll totals")
        body = lines[lines.index(header) + 1 : ni - 1]
        tax_rows = [line for line in body if line.startswith("/401")]
        if len(tax_rows) > 1:
            raise ValueError("Ambiguous ALTEN IRPF")
        tax = None
        if tax_rows:
            prefix = "/401Retenciónacta.IRPF"
            if not tax_rows[0].startswith(prefix):
                raise ValueError("Invalid ALTEN IRPF label")
            tax = _numbers(tax_rows[0].removeprefix(prefix))
            if len(tax) != 3:
                raise ValueError("Invalid ALTEN IRPF cells")
        upper = [
            line.removeprefix("BasesujetaaretenciónIRPF")
            for line in lines[ni + 1 :]
            if line.startswith("BasesujetaaretenciónIRPF")
        ]
        if len(upper) > 1:
            raise ValueError("Ambiguous ALTEN IRPF base")
        upper_values = _numbers(upper[0]) if upper else []
        if len(upper_values) > 1:
            raise ValueError("Ambiguous ALTEN IRPF base")
        identifier = start.strftime("%Y-%m") + "-ALTEN"
        if (
            start.day != 1
            or start.month != end.month
            or start.year != end.year
            or end.day != calendar.monthrange(start.year, start.month)[1]
        ):
            identifier += f"-{start.isoformat()}_{end.isoformat()}"
        # A period identifier, NOT a unique documentary version or payment.
        return self._validate(
            Nomina(
                id=identifier,
                anio=start.year,
                mes=start.month,
                periodo=start.strftime("%Y-%m"),
                empresa=company,
                cif="B05366117",
                fecha_inicio=start.isoformat(),
                fecha_fin=end.isoformat(),
                total_devengado=totals[0][1],
                total_deducir=totals[1][1],
                liquido_percibir=net[0][1],
                irpf_porcentaje=tax[0][1] if tax else None,
                base_irpf=tax[1][1] if tax else None,
                irpf_importe=tax[2][1] if tax else None,
                base_sujeta_retencion_irpf=upper_values[0][1] if upper_values else None,
                salario_base=None,
                plus_convenio=None,
                complementos=None,
                base_ss_comunes=None,
                base_at_ep=None,
                prorrata_pagas_extra=None,
                descuento_seguridad_social=None,
                otras_deducciones=None,
            )
        )

    def parse_extracted(self, document: ExtractedDocument, filename: str = "") -> Nomina:
        if document.pages is not None:
            if len(document.pages) != 1:
                raise ValueError("ALTEN requires one payroll page; use parse_pages")
            document = document.pages[0]
        payroll = self.parse(document.text, filename)
        if not document.words or not document.characters:
            raise ValueError("ALTEN exhaustive parsing requires character layout")
        if len({w.page for w in document.words}) != 1 or {c.page for c in document.characters} != {
            w.page for w in document.words
        }:
            raise ValueError("ALTEN requires one payroll page")
        words, chars = document.words, document.characters
        headings = ("CLAVE", "DESCRIPCIÓN", "UNIDAD", "PRECIO", "DEVENGOS", "DEDUCCIONES")
        anchors = [w for w in words if w.text == "DEVENGOS"]
        if len(anchors) != 1:
            raise ValueError("Missing or ambiguous ALTEN devengos heading")
        anchor = anchors[0]
        candidates = [
            [
                w
                for w in words
                if w.text == h and abs(w.top - anchor.top) < (anchor.bottom - anchor.top) / 4
            ]
            for h in headings
        ]
        if any(len(c) != 1 for c in candidates):
            raise ValueError("Missing or ambiguous ALTEN layout headings")
        heads = [c[0] for c in candidates]
        tolerance = min(w.bottom - w.top for w in heads) / 4
        if any(abs(w.top - heads[0].top) > tolerance for w in heads) or any(
            a.x1 >= b.x0 for a, b in zip(heads, heads[1:])
        ):
            raise ValueError("Ambiguous ALTEN table layout")
        net_top = self._net_top(chars)
        numeric_tops = sorted(
            {
                c.top
                for c in chars
                if heads[0].bottom < c.top < net_top - tolerance and c.text.isdigit()
            }
        )
        if not numeric_tops:
            raise ValueError("Missing ALTEN totals layout")
        end = numeric_tops[-1]
        centers = [(w.x0 + w.x1) / 2 for w in heads[2:]]
        cuts = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
        numeric_start = (heads[1].x1 + heads[2].x0) / 2
        code_words = [
            w
            for w in words
            if heads[0].bottom < w.top < end - tolerance
            and w.x0 < (heads[0].x1 + heads[1].x0) / 2
            and re.fullmatch(r"[A-Z0-9]{4}|/[A-Z0-9]{3}", w.text)
        ]
        concepts = []
        for code in sorted(code_words, key=lambda w: (w.top, w.x0)):
            row = _row(chars, code.top, tolerance)
            description = " ".join(
                "".join(c.text for c in row if code.x1 <= c.x0 < numeric_start).split()
            )
            if not description:
                raise ValueError("Missing ALTEN concept description")
            numbers = _cells([c for c in row if c.x0 >= numeric_start])
            cells: list[list[tuple[str, float, float, float]]] = [[], [], [], []]
            for value in numbers:
                center = (value[2] + value[3]) / 2
                if any(abs(center - cut) < 0.1 for cut in cuts):
                    raise ValueError("Ambiguous ALTEN numeric column")
                index = sum(center > cut for cut in cuts)
                if (index >= 2 and value[2] < cuts[index - 1]) or (
                    index == 2 and value[3] > cuts[2]
                ):
                    raise ValueError("ALTEN amount crosses economic columns")
                cells[index].append(value)
            if any(len(cell) > 1 for cell in cells) or len(cells[2]) + len(cells[3]) != 1:
                raise ValueError("Missing or ambiguous ALTEN concept cells")
            category = _CATEGORIES.get(description, "otro")
            tax = category == "irpf" or category.startswith("cotizacion_")
            amount = (cells[2] or cells[3])[0]
            quantity = cells[0][0][1] if cells[0] else None
            price = cells[1][0][1] if cells[1] else None
            concepts.append(
                ConceptoNomina(
                    codigo=code.text,
                    concepto=description,
                    categoria=category,
                    columna="devengos" if cells[2] else "deducciones",
                    importe=amount[1],
                    importe_texto=amount[0],
                    porcentaje=quantity if tax else None,
                    base=price if tax else None,
                    unidades=None if tax else quantity,
                    precio=None if tax else price,
                )
            )
        # Cross-check cardinality/codes against text: never silently drop a row.
        lines = [_compact(line) for line in document.text.splitlines() if line.strip()]
        begin = lines.index("".join(headings)) + 1
        finish = next(i for i, line in enumerate(lines) if line.startswith("LIQUIDOAPERCIBIR")) - 1
        text_codes = [
            m[0]
            for line in lines[begin:finish]
            if (m := re.match(r"(?:[A-Z0-9]{4}|/[A-Z0-9]{3})(?=[A-Za-zÁÉÍÓÚ])", line))
        ]
        if text_codes != [c.codigo for c in concepts]:
            raise ValueError("ALTEN text/layout concept rows disagree")
        fiscal = [c for c in concepts if c.codigo == "/401"]
        if len(fiscal) > 1 or (
            fiscal
            and (
                fiscal[0].columna != "deducciones"
                or (fiscal[0].porcentaje, fiscal[0].base, fiscal[0].importe)
                != (payroll.irpf_porcentaje, payroll.base_irpf, payroll.irpf_importe)
            )
        ):
            raise ValueError("ALTEN text/layout IRPF disagree")
        bases = self._footer(chars)

        def scalar(category: str) -> float | None:
            entries = [
                c.importe for c in concepts if c.categoria == category and c.columna == "devengos"
            ]
            return entries[0] if len(entries) == 1 else None

        return self._validate(
            replace(
                payroll,
                conceptos=concepts,
                base_ss_comunes=bases["base_ss_comunes"],
                base_at_ep=bases["base_at_ep"],
                base_irpf_pie=bases["base_irpf_pie"],
                base_irpf_especie=bases["base_irpf_especie"],
                prorrata_pagas_extra=bases["prorrata_pagas_extra"],
                pror_otros=bases["pror_otros"],
                salario_base=scalar("salario_base"),
                plus_convenio=scalar("plus_convenio"),
                complementos=scalar("complemento_salarial"),
                fecha_alta=self._header_value(document, "alta:", date_value=True),
                categoria=self._header_value(document, "Profesional:"),
                grupo_cotizacion=self._header_value(document, "Cotización:"),
                categoria_convenio=self._header_value(document, "convenio:"),
            )
        )

    @staticmethod
    def _net_top(chars: tuple[ExtractedWord, ...]) -> float:
        for y in sorted({c.top for c in chars}):
            row = _row(chars, y, 0.5)
            if "LIQUIDOAPERCIBIR" in _compact("".join(c.text for c in row)):
                return y
        raise ValueError("Missing ALTEN net layout")

    @staticmethod
    def _footer(chars: tuple[ExtractedWord, ...]) -> dict[str, float | None]:
        found = []
        for y in sorted({c.top for c in chars}):
            row = sorted(
                (c for c in _row(chars, y, 0.5) if not c.text.isspace()), key=lambda c: c.x0
            )
            plain = "".join(c.text for c in row)
            if plain == "".join(label for label, key in _FOOTER):
                found.append((y, row))
        if len(found) != 1:
            raise ValueError("Missing or ambiguous ALTEN bases headings")
        y, header = found[0]
        centers = []
        pos = 0
        for label, key in _FOOTER:
            cell = header[pos : pos + len(label)]
            pos += len(label)
            centers.append((min(c.x0 for c in cell) + max(c.x1 for c in cell)) / 2)
        if centers != sorted(centers):
            raise ValueError("Invalid ALTEN bases layout")
        cuts = [(a + b) / 2 for a, b in zip(centers, centers[1:])]
        height = max(c.bottom - c.top for c in header)
        values = [c for c in chars if y + height < c.top < y + 3 * height]
        numbers = _cells(values)
        result: dict[str, float | None] = {key: None for label, key in _FOOTER}
        for raw, number, x0, x1 in numbers:
            center = (x0 + x1) / 2
            if any(abs(center - cut) < 0.1 for cut in cuts):
                raise ValueError("Ambiguous ALTEN base cell")
            key = _FOOTER[sum(center > cut for cut in cuts)][1]
            if result[key] is not None:
                raise ValueError("Multiple ALTEN base values in cell")
            result[key] = number
        result.pop("rem_total")
        return result

    @staticmethod
    def _header_value(
        document: ExtractedDocument, label: str, *, date_value: bool = False
    ) -> str | None:
        anchors = [
            w for w in document.words or () if w.text == label or w.text.endswith(" " + label)
        ]
        if len(anchors) > 1:
            raise ValueError("Ambiguous ALTEN header field")
        if not anchors:
            return None
        anchor = anchors[0]
        # Values above underlined labels: retain stream order within the geometry.
        # X-sort alone can place a category's suffix before its prefix.
        value = " ".join(
            "".join(
                c.text
                for c in document.characters or ()
                if anchor.top - (anchor.bottom - anchor.top) < c.top < anchor.top
                and c.x0 >= anchor.x1
            ).split()
        )
        return _iso(value) if value and date_value else value or None
