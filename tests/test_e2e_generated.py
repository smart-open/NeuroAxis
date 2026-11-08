"""W3 upgrade: scenario chains now run GENERATED ST (true end-to-end).

Same scenarios as docs/06 (SC-01/02/04), but the ST under test comes from
plcagent.gen.render(spec) instead of hand-written programs - the chain is
Spec -> IR -> generator -> simulation -> assertions.
"""

from __future__ import annotations

from plcagent.gen import render
from plcagent.scenarios.runner import Expect, run_chain
from plcagent.spec.loader import load_spec
from plcagent.sta import check_ir, check_st

SC01_SPEC = """
specVersion: "1.0"
project: { id: e2e-motor, name: 单电机启停保持, scanMs: 10 }
io:
  digital:
    - { name: Start_PB,  dir: in,  addr: "%I0.0", desc: 启动按钮 }
    - { name: Stop_PB,   dir: in,  addr: "%I0.1", desc: 停止按钮 }
    - { name: EStop_OK,  dir: in,  addr: "%I0.2", desc: 急停正常 }
    - { name: Motor_Run, dir: out, addr: "%Q0.0", desc: 电机运行 }
modes: [Auto]
machines:
  - name: Motor
    initial: Idle
    states:
      - { name: Idle,  entry: [Motor_Run:=0] }
      - { name: Run,   entry: [Motor_Run:=1] }
    transitions:
      - { from: "*",  to: Idle,  when: "Stop_PB OR NOT EStop_OK", prio: 0 }
      - { from: Idle, to: Run,   when: "Start_PB AND EStop_OK", prio: 1 }
interlocks:
  - { when: "NOT EStop_OK", then: [Motor_Run:=0], desc: 急停切断 }
"""

SC02_SPEC = """
specVersion: "1.0"
project: { id: e2e-reversing, name: 电机正反转互锁, scanMs: 10 }
io:
  digital:
    - { name: Fwd_PB,    dir: in,  addr: "%I0.0", desc: 正转按钮 }
    - { name: Rev_PB,    dir: in,  addr: "%I0.1", desc: 反转按钮 }
    - { name: Stop_PB,   dir: in,  addr: "%I0.2", desc: 停止 }
    - { name: EStop_OK,  dir: in,  addr: "%I0.3", desc: 急停正常 }
    - { name: Fwd_Out,   dir: out, addr: "%Q0.0", desc: 正转接触器 }
    - { name: Rev_Out,   dir: out, addr: "%Q0.1", desc: 反转接触器 }
modes: [Auto]
machines:
  - name: Direction
    initial: Stopped
    states:
      - { name: Stopped, entry: [Fwd_Out:=0, Rev_Out:=0] }
      - { name: Forward, entry: [Fwd_Out:=1, Rev_Out:=0] }
      - { name: Reverse, entry: [Fwd_Out:=0, Rev_Out:=1] }
    transitions:
      - { from: "*",     to: Stopped, when: "Stop_PB OR NOT EStop_OK", prio: 0 }
      - { from: Stopped, to: Forward, when: "Fwd_PB AND NOT Rev_PB AND EStop_OK", prio: 1 }
      - { from: Stopped, to: Reverse, when: "Rev_PB AND NOT Fwd_PB AND EStop_OK", prio: 2 }
interlocks:
  - { when: "NOT EStop_OK", then: [Fwd_Out:=0, Rev_Out:=0], desc: 急停双断 }
"""

SC04_SPEC = """
specVersion: "1.0"
project: { id: e2e-modes, name: 手自动模式与急停复位, scanMs: 10 }
io:
  digital:
    - { name: Mode_Auto,  dir: in,  addr: "%I0.0", desc: 自动模式开关 }
    - { name: Start_PB,   dir: in,  addr: "%I0.1", desc: 启动 }
    - { name: Manual_Jog, dir: in,  addr: "%I0.2", desc: 手动点动 }
    - { name: Reset_PB,   dir: in,  addr: "%I0.3", desc: 复位按钮 }
    - { name: EStop_OK,   dir: in,  addr: "%I0.4", desc: 急停正常 }
    - { name: Conv_Run,   dir: out, addr: "%Q0.0", desc: 输送带 }
    - { name: HMI_Fault,  dir: out, addr: "%Q0.1", desc: 故障灯 }
modes: [Auto, Manual]
machines:
  - name: LineCtl
    initial: Idle
    states:
      - { name: Idle,  entry: [Conv_Run:=0, HMI_Fault:=0] }
      - { name: Run,   entry: [Conv_Run:=1] }
      - { name: Fault, entry: [Conv_Run:=0, HMI_Fault:=1] }
    transitions:
      - { from: "*",   to: Fault, when: "NOT EStop_OK", prio: 0 }
      - { from: Fault, to: Idle,  when: "Reset_PB AND EStop_OK", prio: 1 }
      - { from: Idle,  to: Run,   when: "Mode_Auto AND Start_PB AND EStop_OK", prio: 2 }
      - { from: Run,   to: Idle,  when: "NOT Mode_Auto OR NOT Start_PB", prio: 2 }
interlocks:
  - { when: "NOT EStop_OK", then: [Conv_Run:=0], desc: 急停断带 }
  - { when: "NOT Mode_Auto", then: [Conv_Run:=Manual_Jog], desc: 手动点动, manualOnly: true }
"""


def _chain_name(spec_text: str) -> str:
    return load_spec(spec_text).machines[0].name


def _generated(spec_text: str) -> str:
    ir = load_spec(spec_text)
    # gate: IR rules must pass before generation (safety non-disableable)
    assert check_ir(ir) == []
    result = render(ir)
    # gate: generated ST must pass static S-rules
    assert check_st(result.combined) == []
    return result.combined


def test_e2e_sc01_generated_start_stop_hold():
    st = _generated(SC01_SPEC)

    def inputs(scan):
        return {"Mode_Auto": True,
                "Start_PB": scan == 2,
                "Stop_PB": scan == 50,
                "EStop_OK": scan != 80}

    result = run_chain(
        "E2E-SC01", st, scan_ms=10, total_scans=120, input_at=inputs,
        expects=(
            Expect("Motor_Run", True, scan=3, desc="启动脉冲下一扫描吸合"),
            Expect("Motor_Run", True, scan=49, desc="自锁保持"),
            Expect("Motor_Run", False, scan=51, desc="停止释放"),
            Expect("Motor_Run", False, scan=81, desc="急停断开"),
        ),
    )
    assert result.passed, result.failures


def test_e2e_sc02_generated_interlock():
    st = _generated(SC02_SPEC)

    def inputs(scan):
        return {"Mode_Auto": True,
                "Fwd_PB": scan == 2,
                "Rev_PB": scan == 40,
                "Stop_PB": scan == 60,
                "EStop_OK": True}

    result = run_chain(
        "E2E-SC02", st, scan_ms=10, total_scans=90, input_at=inputs,
        expects=(
            Expect("Fwd_Out", True, scan=3, desc="正转吸合"),
            Expect("Rev_Out", False, scan=41, desc="换向无误动"),
            Expect("Fwd_Out", False, scan=61, desc="停止释放"),
        ),
    )
    assert result.passed, result.failures


def test_e2e_sc02_generated_simultaneous_buttons():
    st = _generated(SC02_SPEC)

    def inputs(scan):
        return {"Mode_Auto": True, "Fwd_PB": scan == 2, "Rev_PB": scan == 2,
                "Stop_PB": False, "EStop_OK": True}

    result = run_chain(
        "E2E-SC02X", st, scan_ms=10, total_scans=10, input_at=inputs,
        expects=(
            Expect("Fwd_Out", False, scan=9, desc="同按双键拒动"),
            Expect("Rev_Out", False, scan=9, desc="同按双键拒动"),
        ),
    )
    assert result.passed, result.failures


def test_e2e_sc04_generated_modes_and_reset():
    st = _generated(SC04_SPEC)

    def inputs(scan):
        return {
            "Mode_Auto": 0 <= scan < 60,
            "Start_PB": 10 <= scan < 30,
            "Manual_Jog": 90 <= scan < 110,
            "Reset_PB": scan == 70,
            "EStop_OK": scan != 40,
        }

    result = run_chain(
        "E2E-SC04", st, scan_ms=10, total_scans=140, input_at=inputs,
        expects=(
            Expect("Conv_Run", True, scan=11, desc="自动启动"),
            Expect("HMI_Fault", True, scan=41, desc="急停故障灯"),
            Expect("Conv_Run", False, scan=41, desc="急停断带"),
            Expect("HMI_Fault", False, scan=71, desc="复位清故障"),
            Expect("Conv_Run", True, scan=91, desc="手动点动吸合"),
            Expect("Conv_Run", False, scan=111, desc="点动释放"),
        ),
    )
    assert result.passed, result.failures


def test_e2e_sc04_generated_reset_gate():
    st = _generated(SC04_SPEC)

    def inputs(scan):
        return {
            "Mode_Auto": True,
            "Start_PB": 10 <= scan,
            "Manual_Jog": False,
            "Reset_PB": scan == 90,
            "EStop_OK": scan < 20 or scan >= 90,
        }

    result = run_chain(
        "E2E-SC04R", st, scan_ms=10, total_scans=120, input_at=inputs,
        expects=(
            Expect("Conv_Run", True, scan=11, desc="急停前运行"),
            Expect("Conv_Run", False, scan=30, desc="急停期间断开"),
            Expect("Conv_Run", False, scan=85, desc="未复位 Start 无效"),
            Expect("HMI_Fault", False, scan=91, desc="复位清故障"),
            Expect("Conv_Run", True, scan=92, desc="复位后自动恢复"),
        ),
    )
    assert result.passed, result.failures


def test_e2e_generation_is_deterministic():
    digests = {render(load_spec(SC01_SPEC)).combined for _ in range(3)}
    assert len(digests) == 1
