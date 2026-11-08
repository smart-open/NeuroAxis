"""W3 tests: IR->ST generator + static checker (gen/sta)."""

from __future__ import annotations

import pytest

from plcagent.gen import GenError, render
from plcagent.spec.loader import load_spec
from plcagent.st.interp import Interpreter
from plcagent.st.parser import parse_program
from plcagent.sta import check_ir, check_st
from plcagent.trace.clock import VirtualClock

D1_SPEC = """
specVersion: "1.0"
project: { id: gen-d1, name: 生成器样例, scanMs: 10 }
io:
  digital:
    - { name: Start_PB,   dir: in,  addr: "%I0.0", desc: 启动 }
    - { name: Stop_PB,    dir: in,  addr: "%I0.1", desc: 停止 }
    - { name: EStop_OK,   dir: in,  addr: "%I0.2", desc: 急停正常 }
    - { name: Conv_Run,   dir: out, addr: "%Q0.0", desc: 输送带 }
    - { name: HMI_Fault,  dir: out, addr: "%Q0.1", desc: 故障灯 }
modes: [Auto]
machines:
  - name: Line
    initial: Idle
    states:
      - { name: Idle,  entry: [Conv_Run:=0, HMI_Fault:=0] }
      - { name: Run,   entry: [Conv_Run:=1] }
      - { name: Fault, entry: [Conv_Run:=0, HMI_Fault:=1] }
    transitions:
      - { from: Idle, to: Run,   when: "mode=Auto AND Start_PB AND EStop_OK", prio: 1 }
      - { from: Run,  to: Idle,  when: "Stop_PB", prio: 1 }
      - { from: "*",  to: Fault, when: "NOT EStop_OK", prio: 0 }
interlocks:
  - { when: "NOT EStop_OK", then: [Conv_Run:=0], desc: 急停断带 }
"""


# ---------------- generator ----------------

def _ir(spec_text=D1_SPEC):
    return load_spec(spec_text)


def test_render_is_deterministic():
    first = render(_ir()).combined
    second = render(_ir()).combined
    assert first == second


def test_generated_st_carries_spechash():
    ir = _ir()
    result = render(ir)
    for name, text in result.files.items():
        assert f"SpecHash: {ir.spec_hash}" in text, name


def test_generated_st_parses():
    from plcagent.st.parser import parse_program

    result = render(_ir())
    pou = parse_program(result.combined)      # must not raise
    assert pou.name == "Main"


def test_generated_st_runs_initial_entry_on_first_scan():
    result = render(_ir())
    interp = Interpreter(parse_program(result.combined), VirtualClock(scan_ms=10))
    # EStop_OK defaults FALSE on scan 0 -> wildcard prio-0 edge sends the
    # machine to Fault (correct safety behaviour). Give a healthy first scan.
    interp.run_scan({"EStop_OK": True, "Mode_Auto": False})
    # Idle entry: Conv_Run:=0, HMI_Fault:=0
    assert interp.env.values["Conv_Run"] is False
    assert interp.env.values["HMI_Fault"] is False
    assert interp.env.values["State_Line"] == 0


def test_generated_st_behaves_like_scenario():
    result = render(_ir())
    interp = Interpreter(parse_program(result.combined), VirtualClock(scan_ms=10))
    script = [
        {"Mode_Auto": True, "Start_PB": False, "Stop_PB": False, "EStop_OK": True},
        {"Mode_Auto": True, "Start_PB": True,  "Stop_PB": False, "EStop_OK": True},
        {"Mode_Auto": True, "Start_PB": False, "Stop_PB": False, "EStop_OK": True},
        {"Mode_Auto": True, "Start_PB": False, "Stop_PB": False, "EStop_OK": True},
        {"Mode_Auto": True, "Start_PB": False, "Stop_PB": False, "EStop_OK": False},
        {"Mode_Auto": True, "Start_PB": False, "Stop_PB": False, "EStop_OK": True},
    ]
    values = []
    for inputs in script:
        interp.run_scan(inputs)
        values.append((interp.env.values["Conv_Run"], interp.env.values["HMI_Fault"]))
    assert values[0] == (False, False)   # Idle entry
    assert values[1] == (True, False)    # -> Run
    assert values[3] == (True, False)    # holding
    assert values[4] == (False, True)    # estop -> Fault
    assert values[5] == (False, True)    # fault latched (no reset edge in spec)


def test_mode_enum_renders_as_bool_input():
    text = render(_ir()).combined
    assert "Mode_Auto" in text
    assert "Mode_Auto : BOOL" in text


def test_sequence_member_guard_raises_generror():
    spec = D1_SPEC.replace(
        'when: "Stop_PB", prio: 1',
        'when: "Some_Seq.done", prio: 1')
    # loader allows it (validator knows only real sequences error) -> build a
    # sequence first so V1 passes, then generation must refuse.
    spec = spec.replace("interlocks:", "sequences:\n"
                        "  - name: Some_Seq\n    type: ExtendRetract\n"
                        "    bind: { out: Conv_Run }\ninterlocks:")
    ir = load_spec(spec)
    with pytest.raises(GenError, match="W4"):
        render(ir)


def test_render_files_complete():
    result = render(_ir())
    assert set(result.files) == {
        "GVL_Main.st", "PRG_Main.st", "FB_Machine_Line.st", "PRG_Alarm.st"}


# ---------------- static checker: S rules ----------------

S_OK = """
PROGRAM P
VAR_INPUT A : BOOL; B : BOOL; END_VAR
VAR_OUTPUT X : BOOL; END_VAR
IF A THEN X := TRUE; ELSE X := B; END_IF;
END_PROGRAM
"""


def test_s01_syntax_error_position():
    problems = check_st("PROGRAM P\nVAR A : BOOL;\nA := ;\nEND_PROGRAM")
    s01 = [p for p in problems if p.rule == "S01"]
    assert s01 and s01[0].line == 3


def test_s02_undeclared_variable():
    problems = check_st(
        "PROGRAM P\nVAR_OUTPUT X : BOOL; END_VAR\nX := Ghost;\nEND_PROGRAM")
    assert any(p.rule == "S02" and "Ghost" in p.message for p in problems)


def test_s03_bool_condition_required():
    problems = check_st(
        "PROGRAM P\nVAR N : DINT; END_VAR\nVAR_OUTPUT X : BOOL; END_VAR\n"
        "IF N THEN X := TRUE; END_IF;\nEND_PROGRAM")
    assert any(p.rule == "S03" for p in problems)


def test_s03_assignment_type_mismatch():
    problems = check_st(
        "PROGRAM P\nVAR N : DINT; END_VAR\nVAR_OUTPUT X : BOOL; END_VAR\n"
        "X := N + 1;\nEND_PROGRAM")
    assert any(p.rule == "S03" and "mismatch" in p.message for p in problems)


def test_s11_duplicate_write_same_path():
    problems = check_st(
        "PROGRAM P\nVAR A : BOOL; END_VAR\nVAR_OUTPUT X : BOOL; END_VAR\n"
        "X := TRUE;\nX := A;\nEND_PROGRAM")
    assert any(p.rule == "S11" for p in problems)


def test_s11_mutually_exclusive_branches_allowed():
    """13.5 boundary: assignments in different branches are alternatives."""
    problems = check_st(S_OK)
    assert not any(p.rule == "S11" for p in problems)


def test_s21_direct_address_in_logic():
    problems = check_st(
        "PROGRAM P\nVAR A : BOOL; END_VAR\nVAR_OUTPUT X : BOOL; END_VAR\n"
        "X := A AND %IX0.1;\nEND_PROGRAM")
    assert any(p.rule == "S21" for p in problems)


def test_s21_address_in_comment_ok():
    problems = check_st(
        "PROGRAM P\nVAR A : BOOL; END_VAR\nVAR_OUTPUT X : BOOL; END_VAR\n"
        "// map %I0.0 here\nX := A;\nEND_PROGRAM")
    assert not any(p.rule == "S21" for p in problems)


def test_clean_program_has_no_s_problems():
    problems = check_st(S_OK)
    assert problems == []


# ---------------- static checker: R rules ----------------

def test_r01_power_output_without_interlock_cut():
    """R01 must fire even when the spec-level V13 gate was already passed
    with a different estop arrangement - build the IR directly."""
    ir = _ir()

    # Pydantic frozen models: model_copy(update=...) is the replace() equivalent
    broken = ir.model_copy(update={"interlocks": ()})
    problems = check_ir(broken)
    assert any(p.rule == "R01" and "Conv_Run" in p.message for p in problems)


def test_r02_missing_wildcard_fault_edge():
    ir = _ir()
    machine = ir.machines[0]
    trimmed = machine.model_copy(update={"transitions": tuple(
        t for t in machine.transitions if not (t.from_state == "*"))})
    broken = ir.model_copy(update={"machines": (trimmed,)})
    problems = check_ir(broken)
    assert any(p.rule == "R02" and "wildcard" in p.message for p in problems)


def test_r11_resource_caps():
    ir = _ir()
    base_machine = ir.machines[0]
    nine = tuple(
        base_machine.model_copy(update={"name": f"M{n}"}) for n in range(9))
    problems = check_ir(ir.model_copy(update={"machines": nine}))
    assert any(p.rule == "R11" and "8 machines" in p.message for p in problems)


def test_good_spec_passes_all_r_rules():
    problems = check_ir(_ir())
    assert problems == []


# ---------------- full gate: generated ST passes S rules ----------------

def test_generated_st_is_s_clean():
    result = render(_ir())
    problems = check_st(result.combined)
    assert problems == [], [p.message for p in problems]
