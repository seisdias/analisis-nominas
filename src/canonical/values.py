"""Exact, immutable values; no documentary model or storage dependencies."""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

MIN_COEFFICIENT = -(2**63)
MAX_COEFFICIENT = 2**63 - 1
MAX_SCALE = 9


@dataclass(frozen=True, slots=True)
class ExactDecimal:
    """coefficient * 10**(-scale), in a unique, numerically exact normal form.

    Scale is 0..9. The normalized coefficient fits a signed 64-bit integer.
    Trailing fractional zeros and signed zero are not separate economic values;
    documentary spelling belongs in a separate original-text field.
    """

    coefficient: int
    scale: int

    def __post_init__(self) -> None:
        if type(self.coefficient) is not int or type(self.scale) is not int:
            raise TypeError("Coefficient and scale must be integers, not booleans or floats")
        if not 0 <= self.scale <= MAX_SCALE:
            raise ValueError("Scale must be between 0 and 9")
        coefficient, scale = self.coefficient, self.scale
        if coefficient == 0:
            scale = 0
        else:
            while scale and coefficient % 10 == 0:
                coefficient //= 10
                scale -= 1
        if not MIN_COEFFICIENT <= coefficient <= MAX_COEFFICIENT:
            raise ValueError("Normalized coefficient exceeds the signed 64-bit contract")
        object.__setattr__(self, "coefficient", coefficient)
        object.__setattr__(self, "scale", scale)

    @classmethod
    def from_decimal(cls, value: Decimal) -> "ExactDecimal":
        """Convert without context-dependent rounding or quantization."""
        if not isinstance(value, Decimal):
            raise TypeError("Expected Decimal")
        if not value.is_finite():
            raise ValueError("Non-finite decimal")
        if value.is_zero():
            return cls(0, 0)
        sign, digits, exponent = value.as_tuple()
        assert isinstance(exponent, int)  # Finite Decimals have an integer exponent.
        end = len(digits)
        while end > 1 and digits[end - 1] == 0:
            end -= 1
            exponent += 1
        scale = max(0, -exponent)
        if scale > MAX_SCALE:
            raise ValueError("Decimal cannot fit scale 0..9 without losing precision")
        # Reject enormous exponents before constructing an enormous integer.
        if end + max(0, exponent) > 19:
            raise ValueError("Normalized coefficient exceeds the signed 64-bit contract")
        coefficient = 0
        for digit in digits[:end]:
            coefficient = coefficient * 10 + digit
        coefficient *= 10 ** max(0, exponent)
        return cls(-coefficient if sign else coefficient, scale)

    @classmethod
    def from_text(cls, value: str, *, decimal_separator: str = ".") -> "ExactDecimal":
        """Parse ungrouped ASCII decimal text; separator is explicit, never guessed.

        Optional sign and leading zeros are allowed. Whitespace, exponents,
        grouping, missing integer/fraction digits and non-ASCII digits are rejected.
        """
        if type(value) is not str:
            raise TypeError("Expected decimal text")
        if decimal_separator not in (".", ","):
            raise ValueError("Decimal separator must be '.' or ','")
        separator = re.escape(decimal_separator)
        if not re.fullmatch(rf"[+-]?[0-9]+(?:{separator}[0-9]+)?", value):
            raise ValueError("Invalid ungrouped decimal text")
        return cls.from_decimal(Decimal(value.replace(decimal_separator, ".")))

    def to_decimal(self) -> Decimal:
        """Construct exactly, including under a low-precision Decimal context."""
        digits = tuple(int(digit) for digit in str(abs(self.coefficient)))
        return Decimal((int(self.coefficient < 0), digits, -self.scale))


@dataclass(frozen=True, slots=True)
class CurrencyCode:
    """Three uppercase ASCII letters; format validation, not an ISO registry."""

    code: str

    def __post_init__(self) -> None:
        if type(self.code) is not str:
            raise TypeError("Currency code must be text")
        if not re.fullmatch(r"[A-Z]{3}", self.code):
            raise ValueError("Currency code must contain three uppercase ASCII letters")


class ValueState(StrEnum):
    PRESENT = "present"
    TECHNICAL_NULL = "technical_null"
    NOT_EXTRACTED = "not_extracted"
    NOT_PRESENT = "not_present"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    UNRELIABLE = "unreliable"


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalValue:
    """An explicit state and, when justified, a typed value/candidate.

    A currency can be known even when the amount is absent. None never defaults
    to EUR. Text cannot carry a currency. NOT_APPLICABLE and UNRELIABLE require
    a machine-readable explanation; UNRELIABLE permits no candidate.
    """

    state: ValueState
    value: ExactDecimal | str | None = None
    currency: CurrencyCode | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not ValueState:
            raise TypeError("State must be ValueState")
        if self.value is not None and type(self.value) not in (ExactDecimal, str):
            raise TypeError("Value must be ExactDecimal, text or None")
        if self.currency is not None and type(self.currency) is not CurrencyCode:
            raise TypeError("Currency must be CurrencyCode or None")
        if type(self.value) is str and self.currency is not None:
            raise ValueError("Text cannot carry a currency")
        if self.reason_code is not None:
            if type(self.reason_code) is not str:
                raise TypeError("Reason code must be text")
            if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", self.reason_code):
                raise ValueError("Reason code must be a lowercase dotted identifier")
        if self.state in (ValueState.NOT_APPLICABLE, ValueState.UNRELIABLE):
            if self.reason_code is None:
                raise ValueError("This state requires a reason code")
        if self.state is ValueState.PRESENT:
            if self.value is None:
                raise ValueError("Present requires a value; zero is a valid value")
        elif self.state is not ValueState.UNRELIABLE and self.value is not None:
            raise ValueError("An absence state cannot carry a value")
