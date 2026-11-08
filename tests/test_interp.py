"""Interpreter semantics (15.1 judgement table)."""

import pytest

from plcagent.st.interp import TON, Interpreter, SimFault
from plcagent.st.parser import parse_program
from plcagent.trace.clock import VirtualClock


def make(source: str, scan_ms: int = 10) -> Interpreter:
    return Interpreter(parse_program(source), VirtualClock(scan_ms=scan_ms))


def test_ton_rising_edge_accumulation_and_reset():
    ton = TON(preset_ms=100)
    ton.call(True, 50)
    assert ton.et == 50 and ton.q is False
    ton.call(True, 50)
    assert ton.et == 100 and ton.q is True
    ton.call(False, 50)
    assert ton.et == 0 and ton.q is False  # immediate reset
    ton.call(True, 30)
    assert ton.et == 30  # rising edge restarts


def test_integer_division_truncates_toward_zero():
    interp = make("PROGRAM P\nVAR A : DINT; END_VAR\nA := -7 / 2;\nEND_PROGRAM")
    interp.run_scan({})
    assert interp.env.values["A"] == -3  # C99/matIEC, not floor (-4)


def test_mod_sign_follows_dividend():
    interp = make("PROGRAM P\nVAR A : DINT; END_VAR\nA := -7 MOD 3;\nEND_PROGRAM")
    interp.run_scan({})
    assert interp.env.values["A"] == -1


def test_division_by_zero_raises():
    interp = make("PROGRAM P\nVAR A : DINT; END_VAR\nA := 1 / 0;\nEND_PROGRAM")
    with pytest.raises(SimFault):
        interp.run_scan({})


def test_case_selects_arm_and_else():
    interp = make(
        "PROGRAM P\n"
        "VAR S : DINT; R : DINT; END_VAR\n"
        "CASE S OF\n"
        "  1: R := 10;\n"
        "  2, 3: R := 20;\n"
        "ELSE\n"
        "  R := 99;\n"
        "END_CASE;\n"
        "END_PROGRAM"
    )
    interp.run_scan({"S": 3})
    assert interp.env.values["R"] == 20
    interp.run_scan({"S": 7})
    assert interp.env.values["R"] == 99


def test_for_final_value_is_stop_plus_step():
    interp = make(
        "PROGRAM P\n"
        "VAR I : DINT; LAST : DINT; SUM : DINT; END_VAR\n"
        "FOR I := 1 TO 5 DO\n"
        "  SUM := SUM + I;\n"
        "END_FOR;\n"
        "LAST := I;\n"
        "END_PROGRAM"
    )
    interp.run_scan({})
    assert interp.env.values["SUM"] == 15
    assert interp.env.values["LAST"] == 6  # IEC definition (15.1)


def test_unknown_input_rejected():
    interp = make("PROGRAM P\nVAR A : BOOL; END_VAR\nA := TRUE;\nEND_PROGRAM")
    with pytest.raises(SimFault):
        interp.run_scan({"Ghost": True})
