"""ST value model - strict, deterministic, no implicit conversion.

Semantics per docs 15.1:
- integers wrap on overflow like matIEC/C (two's complement)
- REAL is IEEE754 single precision, rounded on every write
- TIME has 1 ms resolution
- BOOL admits only real bools (no int->bool coercion, S03)
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass


class StTypeError(ValueError):
    """Raised when a value does not match its declared type."""


@dataclass(frozen=True, slots=True)
class StType:
    name: str

    def __repr__(self) -> str:
        return self.name


BOOL = StType("BOOL")
BYTE = StType("BYTE")
INT = StType("INT")
DINT = StType("DINT")
UINT = StType("UINT")
UDINT = StType("UDINT")
REAL = StType("REAL")
TIME = StType("TIME")
STRING = StType("STRING")

BY_NAME: dict[str, StType] = {
    t.name: t for t in (BOOL, BYTE, INT, DINT, UINT, UDINT, REAL, TIME, STRING)
}

INT_RANGE: dict[StType, tuple[int, int]] = {
    BYTE: (0, 255),
    INT: (-32768, 32767),
    DINT: (-(2**31), 2**31 - 1),
    UINT: (0, 65535),
    UDINT: (0, 2**32 - 1),
}


def _wrap(value: int, lo: int, hi: int) -> int:
    """Two's-complement wraparound, matching matIEC/C behaviour."""
    span = hi - lo + 1
    return ((value - lo) % span) + lo


def coerce(st_type: StType, value: object) -> object:
    """Coerce a Python value into the strict ST representation for st_type."""
    if st_type is BOOL:
        if isinstance(value, bool):
            return value
        raise StTypeError(f"BOOL requires bool, got {type(value).__name__}")

    if st_type in INT_RANGE:
        if isinstance(value, bool) or not isinstance(value, int):
            raise StTypeError(f"{st_type.name} requires int, got {type(value).__name__}")
        lo, hi = INT_RANGE[st_type]
        return _wrap(value, lo, hi)

    if st_type is REAL:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StTypeError(f"REAL requires number, got {type(value).__name__}")
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise StTypeError("REAL forbids NaN/Inf (determinism)")
        # IEEE754 single-precision round trip (15.1).
        return struct.unpack("<f", struct.pack("<f", float(value)))[0]

    if st_type is TIME:
        if isinstance(value, bool) or not isinstance(value, int):
            raise StTypeError(f"TIME requires int milliseconds, got {type(value).__name__}")
        return value

    if st_type is STRING:
        if not isinstance(value, str):
            raise StTypeError(f"STRING requires str, got {type(value).__name__}")
        return value[:80]  # fixed 80 chars, overlong truncated (S08)

    raise StTypeError(f"unsupported type {st_type.name}")


def default_value(st_type: StType) -> object:
    """Zero-value initialisation: BOOL=FALSE, numbers=0, STRING=''."""
    if st_type is BOOL:
        return False
    if st_type is REAL:
        return 0.0
    if st_type is STRING:
        return ""
    return 0
