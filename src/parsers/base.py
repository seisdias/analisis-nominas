from abc import ABC, abstractmethod
from math import isfinite

from src.extraction import ExtractedDocument
from src.models.nomina import Nomina


class BaseParser(ABC):
    @abstractmethod
    def parse(self, text: str, filename: str = "") -> Nomina:
        """Parse extracted text; reject missing essential fields explicitly."""
        raise NotImplementedError

    def parse_extracted(self, document: ExtractedDocument, filename: str = "") -> Nomina:
        """Compatible entry point; layout-aware parsers may override this hook."""
        return self.parse(document.text, filename=filename)

    @staticmethod
    def _validate(doc: Nomina) -> Nomina:
        if not 1 <= doc.mes <= 12 or not 1900 <= doc.anio <= 9999:
            raise ValueError("Invalid or missing payroll period")
        amounts = (doc.total_devengado, doc.total_deducir, doc.liquido_percibir)
        if not all(isfinite(value) for value in amounts):
            raise ValueError("Non-finite payroll total")
        if abs(doc.total_devengado - doc.total_deducir - doc.liquido_percibir) > 0.02:
            raise ValueError("Payroll totals do not balance")
        return doc
