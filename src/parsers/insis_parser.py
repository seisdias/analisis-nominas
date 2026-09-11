"""Text-only INSIS4 payrolls. Dates and amounts always come from the document."""

import re
import unicodedata
from datetime import date
from math import isfinite

from src.models.documento_laboral import TipoDocumento
from src.models.nomina import Nomina
from src.parsers.base import BaseParser

_MONEY = r"-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}"
_MONTHS = dict(enumerate((
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
), start=1))


def _parse_money(raw: str) -> float:
    if not re.fullmatch(_MONEY, raw):
        raise ValueError("Invalid INSIS4 amount")
    value = float(raw.replace(".", "").replace(",", "."))
    if not isfinite(value):
        raise ValueError("Invalid INSIS4 amount")
    return value


def _compact(line: str) -> str:
    normalized = unicodedata.normalize("NFD", line.upper())
    compact = "".join(c for c in normalized if not c.isspace() and not unicodedata.combining(c))
    # Only the old letter-spaced A/B total rows have leaders printed over digits.
    if re.search(r"T[ \t]+O[ \t]+T[ \t]+A[ \t]+L", line.upper()):
        for label in ("A.TOTALDEVENGADO", "B.TOTALADEDUCIR"):
            if compact.startswith(label) and compact[len(label):].startswith(".."):
                compact = label + compact[len(label):].replace(".", "")
    return compact


def _amount(tail: str, field: str, *, blank: bool = False, column: bool = False) -> float:
    # Strip leading filler only; punctuation inside a money token must be valid.
    tail = tail.lstrip(".")
    if not tail:
        if blank:
            return 0.0  # An explicitly empty optional cell, never another row's number.
        raise ValueError(f"Missing INSIS4 amount: {field}")
    match = re.match(rf"({_MONEY})(?![\d.,])", tail)
    if not match:
        raise ValueError(f"Invalid INSIS4 amount: {field}")
    suffix = tail[match.end():]
    next_columns = {
        "SALARIOBASE": r"INDEMNIZACIONESOSUPLIDOS:",
        "CTA.CONVEN": r"PRESTACIONESEINDEMNIZACIONESDELASEG\.SOC\.:",
        "TOTALAPORTACIONES": rf"B\.TOTALADEDUCIR\(1\+2\+3\+4\+5\+6\+7\)({_MONEY})",
        "PRORRATAPAGASEXTRAORDINARIAS": rf"PROFESIONAL,FONDODEGARANTIASALARIAL\)({_MONEY})",
    }
    if suffix:
        boundary = re.fullmatch(next_columns.get(field, r"(?!)"), suffix) if column else None
        if boundary is None:
            raise ValueError(f"Invalid INSIS4 amount: {field} (unexpected column content)")
        for amount in boundary.groups():
            _parse_money(amount)
    return _parse_money(match.group(1))


def _cell(rows: list[str], label: str, *, blank: bool = False,
          column: bool = False, absent: bool = False) -> float:
    tails = [row.split(label, 1)[1] for row in rows if label in row]
    if not tails and absent:
        return 0.0
    if len(tails) != 1:
        raise ValueError(f"Missing or ambiguous INSIS4 field: {label}")
    return _amount(tails[0], label, blank=blank, column=column)


class InsisParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        if not text.strip():
            raise ValueError("Missing payroll period: empty INSIS4 text (OCR not supported)")
        rows = [_compact(line) for line in text.splitlines() if line.strip()]
        if not any(re.search(r"B84225283(?!\d)", row) for row in rows):
            raise ValueError("Not an INSIS4 payroll: missing or different CIF")

        period_rows = [row for row in rows if "PERIODODELIQUIDACION:" in row]
        if len(period_rows) != 1:
            raise ValueError("Missing or ambiguous payroll period")
        extra = "PAGAEXTRA" in period_rows[0]
        year, month = self._period(rows, period_rows[0], extra)
        kind = TipoDocumento.PAGA_EXTRA if extra else TipoDocumento.NOMINA_ORDINARIA

        gross = _cell(rows, "A.TOTALDEVENGADO")
        deduction_rows = [row for row in rows if "B.TOTALADEDUCIR" in row]
        if len(deduction_rows) != 1:
            raise ValueError("Missing or ambiguous INSIS4 field: total_deducir")
        tail = deduction_rows[0].split("B.TOTALADEDUCIR", 1)[1]
        tail = re.sub(r"^\(1\+2\+3\+4\+5\+6\+7\)", "", tail)
        deductions = _amount(tail, "total_deducir")
        net_rows = [row for row in rows if "LIQUIDOTOTALAPERCIBIR" in row]
        if len(net_rows) != 1:
            raise ValueError("Missing or ambiguous INSIS4 field: liquido_percibir")
        currency = re.search(r"(?:PTA|EUROS)(.*)$", net_rows[0])
        if not currency:
            raise ValueError("Missing INSIS4 amount: liquido_percibir")
        net = _amount(currency.group(1), "liquido_percibir")

        try:
            start = next(i for i, row in enumerate(rows) if row.startswith("I.DEVENGOS"))
            end = next(i for i, row in enumerate(rows) if "A.TOTALDEVENGADO" in row)
        except StopIteration:
            raise ValueError("Missing INSIS4 earnings section") from None
        earnings = rows[start + 1:end]
        salary = _cell(earnings, "SALARIOBASE", blank=extra, column=True)
        agreement_label = "PLUSCONVENIO" if any("PLUSCONVENIO" in r for r in earnings) else "P.CONVENIO"
        agreement = _cell(earnings, agreement_label, column=True, absent=extra)
        supplements = sum(
            _cell(earnings, label, column=True, absent=True)
            for label in ("INCENTIVOS", "GRAT.VOL.ABS.", "TRANSPORTE", "ATRASOS")
        )
        # Same concept, two spellings; do not count a substring twice.
        for row in earnings:
            match = re.match(r"(?:A)?CTA\.CONV(?:EN)?(.*)", row)
            if match:
                supplements += _amount(match.group(1), "CTA.CONVEN", column=True)
        if extra:
            supplements += self._extra_amount(earnings)

        social = _cell(rows, "TOTALAPORTACIONES", blank=extra, column=True)
        rate, tax = self._irpf(rows)
        advance = _cell(rows, "ANTICIPOS", blank=True, absent=True)
        # These bases are printed in their own footer, including in the extra template.
        base_tax = _cell(rows, "4.BASESUJETAARETENCIONDELI.R.P.F.")
        prorrata = _cell(rows, "PRORRATAPAGASEXTRAORDINARIAS", blank=extra, column=True)
        base_rows = [row.split("4.BASE", 1)[0] for row in rows
                     if re.match(r"TOTAL(?:\.|\d|$)", row)]
        base_social = _cell(base_rows, "TOTAL", blank=extra)

        doc = self._validate(Nomina(
            id=f"insis4-{year:04d}-{month:02d}-{kind.value.lower()}",
            tipo=kind, anio=year, mes=month, periodo=f"{year:04d}-{month:02d}",
            empresa="INTELIGENCIA SISTEMATICA 4, S.L.", cif="B84225283",
            salario_base=salary, plus_convenio=agreement,
            complementos=round(supplements, 2), prorrata_pagas_extra=prorrata,
            total_devengado=gross, descuento_seguridad_social=social,
            irpf_porcentaje=rate, irpf_importe=tax, otras_deducciones=advance,
            total_deducir=deductions, liquido_percibir=net,
            base_ss_comunes=base_social, base_irpf=base_tax,
            observaciones=f"Procesado desde {filename}",
        ))
        # Prorrata in the contribution footer is not a second payroll earning.
        if abs(salary + agreement + supplements - gross) > 0.02:
            raise ValueError("INSIS4 earnings do not balance: unsupported or missing concept")
        if abs(social + tax + advance - deductions) > 0.02:
            raise ValueError("INSIS4 deductions do not balance: unsupported or missing concept")
        return doc

    @staticmethod
    def _period(rows: list[str], period: str, extra: bool) -> tuple[int, int]:
        months = {name: number for number, name in _MONTHS.items()}
        if extra:
            # Extra's document date assigns its month; no accrual interval is inferred.
            candidates = set()
            for row in rows:
                match = re.fullmatch(r"(?:FIRMAYSELLODELAEMPRESA)?(?:MADRID,?)?(\d{1,2})DE([A-Z]+)DE(\d{4})", row)
                if match and match.group(2) in months:
                    try:
                        observed = date(int(match.group(3)), months[match.group(2)], int(match.group(1)))
                    except ValueError:
                        raise ValueError("Invalid payroll period date") from None
                    candidates.add((observed.year, observed.month))
            if len(candidates) != 1:
                raise ValueError("Missing or ambiguous payroll period for extra")
            return candidates.pop()
        match = re.search(r"DE([A-Z]+)DE(\d{4})", period)
        if not match or match.group(1) not in months:
            raise ValueError("Missing or invalid payroll period")
        return int(match.group(2)), months[match.group(1)]

    @staticmethod
    def _extra_amount(rows: list[str]) -> float:
        indices = [i for i, row in enumerate(rows) if row.startswith("GRATIFICACIONESEXTR.")]
        if len(indices) != 1:
            raise ValueError("Missing or ambiguous INSIS4 extra earning")
        i = indices[0]
        tail = rows[i].removeprefix("GRATIFICACIONESEXTR.")
        if tail:
            return _amount(tail, "extra earning")
        # pdfplumber can place the sole standalone amount just above its label.
        adjacent = [rows[j] for j in (i - 1, i + 1) if 0 <= j < len(rows)
                    and re.fullmatch(_MONEY, rows[j])]
        if len(adjacent) != 1:
            raise ValueError("Missing or ambiguous INSIS4 extra earning")
        return _parse_money(adjacent[0])

    @staticmethod
    def _irpf(rows: list[str]) -> tuple[float, float]:
        tails = []
        for row in rows:
            for label in ("2.IMPUESTOSOBRELARENTA.", "2.I.R.P.F."):
                if label in row:
                    tails.append(row.split(label, 1)[1].lstrip("."))
        if len(tails) != 1:
            raise ValueError("Missing or ambiguous INSIS4 IRPF")
        match = re.fullmatch(rf"(\d+,\d{{2}})%?({_MONEY})(?:\(ABONOIRPF.*\))?", tails[0])
        if not match:
            raise ValueError("Invalid INSIS4 IRPF amount or percentage")
        rate, amount = _parse_money(match.group(1)), _parse_money(match.group(2))
        if not 0 <= rate <= 100:
            raise ValueError("Invalid INSIS4 IRPF percentage")
        return rate, amount
