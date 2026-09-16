import re

from src.parsers.alten_parser import AltenParser
from src.parsers.altran_parser import AltranParser
from src.parsers.base import BaseParser
from src.parsers.coritel_parser import CoritelParser
from src.parsers.exceltic_parser import ExcelticParser
from src.parsers.ineco_parser import InecoParser
from src.parsers.insis_parser import InsisParser


class ParserFactory:
    def __init__(self) -> None:
        self._parsers: dict[str, BaseParser] = {
            "alten": AltenParser(), "altran": AltranParser(),
            "coritel": CoritelParser(), "exceltic": ExcelticParser(),
            "ineco": InecoParser(), "insis": InsisParser(),
        }

    def obtener_parser(self, empresa_o_texto: str) -> BaseParser:
        value = empresa_o_texto.casefold()
        if "inteligencia sistematica" in value:
            value += " insis"
        if re.search(r"\ba28220168\b", value):
            value += " ineco"
        matches = [parser for key, parser in self._parsers.items() if key in value]
        if len(matches) != 1:
            raise ValueError("Unknown or ambiguous payroll format; specify the company")
        return matches[0]
