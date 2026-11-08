"""Value model semantics (15.1)."""

import struct

import pytest

from plcagent.st.types import BOOL, BYTE, DINT, INT, REAL, coerce, default_value


def test_int_wraps_on_overflow_like_matiec():
    assert coerce(DINT, 2**31) == -(2**31)
    assert coerce(INT, 32767 + 1) == -32768


def test_byte_range_wraps():
    assert coerce(BYTE, 255) == 255
    assert coerce(BYTE, 256) == 0


def test_real_is_float32_rounded():
    value = coerce(REAL, 0.1)
    assert value != 0.1  # double 0.1 differs from float32 0.1
    assert value == struct.unpack("<f", struct.pack("<f", 0.1))[0]


def test_real_forbids_nan_inf():
    with pytest.raises(ValueError):
        coerce(REAL, float("nan"))


def test_bool_admits_only_bool():
    with pytest.raises(ValueError):
        coerce(BOOL, 1)  # no implicit int->bool (S03)


def test_default_values():
    assert default_value(BOOL) is False
    assert default_value(REAL) == 0.0
    assert default_value(DINT) == 0
