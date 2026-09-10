from src.models.nomina import Nomina
from src.parsers.base import BaseParser


class CoritelParser(BaseParser):
    def parse(self, text: str, filename: str = "") -> Nomina:
        raise NotImplementedError("Coritel extraction is not implemented; no payroll is produced")
