"""W2 spec engine tests: expression parser, schema, IR build, V-rules, version chain."""

from __future__ import annotations

import pytest

from plcagent.spec.expr import SpecExprError, parse_spec_expr
from plcagent.spec.ir_model import IrExpr
from plcagent.spec.loader import SpecError, load_spec, load_spec_text, spec_hash
from plcagent.spec.validator import validate
from plcagent.spec.versioning import SpecVersionChain, VersionConflict

D1_SPEC = """
specVersion: "1.0"
project: { id: demo-d1, name: 输送线分拣D1, scanMs: 10 }

io:
  digital:
    - { name: EStop_OK,       dir: in,  addr: "%I0.0", desc: 急停正常 }
    - { name: Start_PB,       dir: in,  addr: "%I0.1", desc: 启动 }
    - { name: Stop_PB,        dir: in,  addr: "%I0.2", desc: 停止 }
    - { name: PE_SortPos,     dir: in,  addr: "%I0.4", desc: 分拣位光电 }
    - { name: Cyl1_Extended,  dir: in,  addr: "%I0.5", desc: 伸出到位 }
    - { name: Cyl1_Retracted, dir: in,  addr: "%I0.6", desc: 缩回到位 }
    - { name: Conv_Run,       dir: out, addr: "%Q0.0", desc: 输送带 }
    - { name: Cyl1_Out,       dir: out, addr: "%Q0.1", desc: 推料阀 }
    - { name: HMI_Running,    dir: out, addr: "%Q0.2", desc: 运行灯 }
    - { name: HMI_Fault,      dir: out, addr: "%Q0.3", desc: 故障灯 }

modes: [Auto, Manual]
params:
  - { name: SortTimeOut, type: TIME, value: 2s, desc: 分拣超时 }

machines:
  - name: ConvLine
    initial: Idle
    states:
      - { name: Idle,    entry: [Conv_Run:=0, Cyl1_Out:=0] }
      - { name: Running, entry: [HMI_Running:=1] }
      - { name: Sorting, entry: [Conv_Run:=0] }
      - { name: Fault,   entry: [Conv_Run:=0, Cyl1_Out:=0, HMI_Fault:=1] }
    transitions:
      - { from: Idle,    to: Running, when: "mode=Auto AND Start_PB AND EStop_OK", prio: 1 }
      - { from: Running, to: Idle,    when: "Stop_PB OR NOT EStop_OK", prio: 1 }
      - { from: Running, to: Sorting, when: "PE_SortPos", prio: 2 }
      - { from: Sorting, to: Running, when: "Cyl1_Seq.done", prio: 1 }
      - { from: "*",     to: Fault,   when: "Cyl1_Seq.fault", prio: 0 }

sequences:
  - name: Cyl1_Seq
    type: ExtendRetract
    bind: { out: Cyl1_Out, ext: Cyl1_Extended, ret: Cyl1_Retracted, timeout: SortTimeOut }

interlocks:
  - { when: "NOT EStop_OK", then: [Conv_Run:=0, Cyl1_Out:=0], desc: 急停切断 }

alarms:
  - { code: AL01, cond: "Cyl1_Seq.fault", text: 推料缸超时, level: fault }
"""


# ---------------- expression parser ----------------

def test_expr_precedence():
    tree = parse_spec_expr("A OR B AND NOT C")
    # OR at root, AND below, NOT innermost
    assert tree.kind == "BIN" and tree.op == "OR"
    assert tree.right.kind == "BIN" and tree.right.op == "AND"
    assert tree.right.right.kind == "NOT"


def test_expr_member_and_cmp():
    tree = parse_spec_expr("mode=Auto AND Cyl1_Seq.done")
    assert tree.op == "AND"
    assert tree.left.kind == "CMP"
    assert tree.right.kind == "MEMBER"
    assert tree.right.name == "Cyl1_Seq"


def test_expr_time_literal_to_ms():
    tree = parse_spec_expr("T#2s <= SortTimeOut")
    assert tree.left.kind == "LIT" and tree.left.value == 2000


def test_expr_errors_have_position():
    with pytest.raises(SpecExprError, match="position"):
        parse_spec_expr("A AND")
    with pytest.raises(SpecExprError):
        parse_spec_expr("   ")


def test_expr_parentheses():
    tree = parse_spec_expr("(A OR B) AND C")
    assert tree.op == "AND"
    assert tree.left.op == "OR"


# ---------------- schema + loading ----------------

def test_load_d1_spec_end_to_end():
    project = load_spec(D1_SPEC)
    assert project.scan_ms == 10
    assert len(project.io) == 10
    assert len(project.machines) == 1
    machine = project.machines[0]
    assert machine.initial_state == "Idle"
    assert len(machine.transitions) == 5
    # guard must be a tree, not a string
    assert isinstance(machine.transitions[0].guard, IrExpr)
    assert project.params[0].value == 2000        # 2s -> 2000 ms
    assert project.sequences[0].template == "ExtendRetract"


def test_spec_hash_stable_and_sensitive():
    h1 = spec_hash(load_spec_text(D1_SPEC))
    h2 = spec_hash(load_spec_text(D1_SPEC))
    assert h1 == h2
    modified = D1_SPEC.replace("scanMs: 10", "scanMs: 20")
    assert spec_hash(load_spec_text(modified)) != h1


def test_schema_rejects_bad_scan_ms():
    bad = D1_SPEC.replace("scanMs: 10", "scanMs: 7")
    with pytest.raises(SpecError, match="schema validation failed"):
        load_spec(bad)


def test_schema_rejects_unknown_field():
    bad = D1_SPEC + "\nbogusField: 1\n"
    with pytest.raises(SpecError, match="schema"):
        load_spec(bad)


def test_expression_error_reports_machine():
    bad = D1_SPEC.replace("when: \"PE_SortPos\"", "when: \"PE_SortPos AND(\"")
    with pytest.raises(SpecError, match="machine 'ConvLine'"):
        load_spec(bad)


# ---------------- semantic validator ----------------

def _loaded():
    return load_spec(D1_SPEC)


def test_valid_d1_has_no_errors():
    problems = validate(_loaded())
    errors = [p for p in problems if p.level == "error"]
    assert errors == []


def test_v1_unknown_reference():
    project = _loaded()
    bad = D1_SPEC.replace("when: \"PE_SortPos\"", "when: \"NoSuchSignal\"")
    data = load_spec_text(bad)
    from plcagent.spec.loader import build_ir

    broken = build_ir(data)
    codes = {p.code for p in validate(broken)}
    assert "V1" in codes
    assert project is not None


def test_v4_unreachable_state_detected():
    # remove the transition into Sorting -> unreachable
    bad = D1_SPEC.replace(
        "      - { from: Running, to: Sorting, when: \"PE_SortPos\", prio: 2 }\n", "")
    data = load_spec_text(bad)
    from plcagent.spec.loader import build_ir

    problems = validate(build_ir(data))
    assert any(p.code == "V4" and "Sorting" in p.message for p in problems)


def test_v6_duplicate_priority_detected():
    bad = D1_SPEC.replace(
        "when: \"PE_SortPos\", prio: 2", "when: \"PE_SortPos\", prio: 1")
    data = load_spec_text(bad)
    from plcagent.spec.loader import build_ir

    problems = validate(build_ir(data))
    assert any(p.code == "V6" for p in problems)


def test_v13_estop_interlock_required():
    bad = D1_SPEC.replace(
        '  - { when: "NOT EStop_OK", then: [Conv_Run:=0, Cyl1_Out:=0], desc: 急停切断 }\n', "")
    data = load_spec_text(bad)
    from plcagent.spec.loader import build_ir

    problems = validate(build_ir(data))
    assert any(p.code == "V13" for p in problems)


def test_v16_dead_io_warn_only():
    # add an unused IO -> warn, load_spec must still succeed
    bad = D1_SPEC.replace(
        "    - { name: HMI_Fault,      dir: out, addr: \"%Q0.3\", desc: 故障灯 }",
        "    - { name: HMI_Fault,      dir: out, addr: \"%Q0.3\", desc: 故障灯 }\n"
        "    - { name: Spare_Out,      dir: out, addr: \"%Q0.7\", desc: 备用 }")
    project = load_spec(bad)   # warn must not block
    problems = validate(project)
    assert any(p.code == "V16" and "Spare_Out" in p.message for p in problems)


# ---------------- version chain ----------------

def test_version_chain_commit_and_integrity():
    chain = SpecVersionChain("demo-d1")
    v1 = chain.commit(D1_SPEC, author="human")
    v2 = chain.commit(D1_SPEC.replace("scanMs: 10", "scanMs: 20"), author="human")
    assert v1.seq == 1 and v2.seq == 2
    assert chain.latest().seq == 2
    assert chain.verify_integrity()
    chain.approve(1, by_user="alice")
    assert chain.get(1).approved_by == "alice"


def test_version_chain_range_check():
    chain = SpecVersionChain("demo-d1")
    with pytest.raises(VersionConflict):
        chain.latest()
    chain.commit(D1_SPEC, author="human")
    with pytest.raises(VersionConflict):
        chain.get(5)
