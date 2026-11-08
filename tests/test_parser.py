"""Parser behaviour incl. 15.1 literal semantics."""

import pytest

from plcagent.st.lexer import StSyntaxError
from plcagent.st.parser import parse_program, parse_time_ms


def test_parse_simple_program():
    pou = parse_program(
        "PROGRAM Main\n"
        "VAR_INPUT Run : BOOL; END_VAR\n"
        "VAR_OUTPUT Motor : BOOL; END_VAR\n"
        "Motor := Run;\n"
        "END_PROGRAM"
    )
    assert pou.name == "Main"
    assert len(pou.decls) == 2
    assert len(pou.body) == 1


def test_syntax_error_carries_position():
    with pytest.raises(StSyntaxError) as exc:
        parse_program("PROGRAM P\n Run := ;\nEND_PROGRAM")
    assert exc.value.line == 2


def test_time_literals_floor_to_ms():
    assert parse_time_ms("T#2s") == 2000
    assert parse_time_ms("T#3500ms") == 3500
    assert parse_time_ms("TIME#1m30s") == 90_000
    assert parse_time_ms("T#1.5s") == 1500


def test_and_binds_tighter_than_or():
    pou = parse_program(
        "PROGRAM P\n"
        "VAR X : BOOL; A : BOOL; B : BOOL; C : BOOL; END_VAR\n"
        "X := A OR B AND C;\n"
        "END_PROGRAM"
    )
    assert pou.body[0].expr.op == "OR"


def test_case_with_multi_label_arms():
    pou = parse_program(
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
    case = pou.body[0]
    assert len(case.arms) == 2
    assert case.arms[1].labels == (2, 3)
    assert len(case.else_body) == 1
