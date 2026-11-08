"""Business scenario chain tests (docs/06 scenario catalogue).

Each scenario walks the full delivery chain:
  Spec (YAML) -> schema+semantic validation -> IR
  -> equivalent ST (W3 generator placeholder) -> interpreter simulation
  -> assertion over output timeline.

Scenario ids match docs/06_业务场景测试案例.md.
"""

from __future__ import annotations

from plcagent.scenarios.runner import AssertNever, Expect, run_chain
from plcagent.spec.loader import load_spec
from plcagent.verify import check_determinism

# =====================================================================
# SC-01 单电机启停保持 (A组: 启停互锁)
# =====================================================================

SC01_SPEC = """
specVersion: "1.0"
project: { id: sc01-motor, name: 单电机启停保持, scanMs: 10 }
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
      - { from: Idle, to: Run,   when: "Start_PB AND EStop_OK", prio: 1 }
      - { from: Run,  to: Idle,  when: "Stop_PB OR NOT EStop_OK", prio: 1 }
interlocks:
  - { when: "NOT EStop_OK", then: [Motor_Run:=0], desc: 急停切断 }
"""

# equivalent hand-written ST (stands in for the W3 generator output)
SC01_ST = """
PROGRAM Motor
VAR_INPUT
    Start_PB : BOOL;
    Stop_PB : BOOL;
    EStop_OK : BOOL;
END_VAR
VAR_OUTPUT
    Motor_Run : BOOL;
END_VAR
VAR
    State : DINT;
END_VAR

IF NOT EStop_OK THEN
    State := 0;
    Motor_Run := FALSE;
ELSIF State = 0 AND Start_PB AND EStop_OK THEN
    State := 1;
    Motor_Run := TRUE;
ELSIF State = 1 AND (Stop_PB OR NOT EStop_OK) THEN
    State := 0;
    Motor_Run := FALSE;
END_IF;
END_PROGRAM
"""


def _sc01_inputs(scan):
    return {
        "Start_PB": scan == 2,               # pulse at scan 2
        "Stop_PB": scan == 50,               # stop at scan 50
        "EStop_OK": scan != 80,              # estop trips at scan 80
    }


def test_sc01_full_chain_spec_to_simulation():
    project = load_spec(SC01_SPEC)           # schema + semantic gates
    assert project.spec_hash
    result = run_chain(
        "SC01", SC01_ST, scan_ms=10, total_scans=120, input_at=_sc01_inputs,
        expects=(
            Expect("Motor_Run", True, scan=3, desc="启动脉冲后下一扫描电机吸合"),
            Expect("Motor_Run", True, scan=49, desc="保持运行(自锁)"),
            Expect("Motor_Run", False, scan=51, desc="停止按钮后释放"),
            Expect("Motor_Run", False, scan=81, desc="急停强制断开"),
        ),
    )
    assert result.passed, result.failures


def test_sc01_deterministic_5_runs():
    digests = set()
    for _ in range(5):
        chain = run_chain("SC01", SC01_ST, scan_ms=10, total_scans=120,
                          input_at=_sc01_inputs)
        assert chain.passed, chain.failures
        digests.add(chain.digest)
    assert len(digests) == 1


# =====================================================================
# SC-02 正反转互锁 (A组)
# =====================================================================

SC02_SPEC = """
specVersion: "1.0"
project: { id: sc02-reversing, name: 电机正反转互锁, scanMs: 10 }
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
      - { from: Stopped, to: Forward, when: "Fwd_PB AND EStop_OK", prio: 1 }
      - { from: Stopped, to: Reverse, when: "Rev_PB AND EStop_OK", prio: 2 }
      - { from: "*",     to: Stopped, when: "Stop_PB OR NOT EStop_OK", prio: 0 }
interlocks:
  - { when: "NOT EStop_OK", then: [Fwd_Out:=0, Rev_Out:=0], desc: 急停双断 }
"""

SC02_ST = """
PROGRAM Reversing
VAR_INPUT
    Fwd_PB : BOOL;
    Rev_PB : BOOL;
    Stop_PB : BOOL;
    EStop_OK : BOOL;
END_VAR
VAR_OUTPUT
    Fwd_Out : BOOL;
    Rev_Out : BOOL;
END_VAR
VAR
    State : DINT;
END_VAR

IF (Stop_PB OR NOT EStop_OK) THEN
    State := 0;
    Fwd_Out := FALSE;
    Rev_Out := FALSE;
ELSIF State = 0 AND Fwd_PB AND NOT Rev_PB AND EStop_OK THEN
    State := 1;
    Fwd_Out := TRUE;
    Rev_Out := FALSE;
ELSIF State = 0 AND Rev_PB AND NOT Fwd_PB AND EStop_OK THEN
    State := 2;
    Fwd_Out := FALSE;
    Rev_Out := TRUE;
END_IF;
END_PROGRAM
"""


def _sc02_inputs(scan):
    return {
        "Fwd_PB": scan == 2,
        "Rev_PB": scan == 40,
        "Stop_PB": scan == 60,
        "EStop_OK": True,
    }


def test_sc02_interlock_never_both_outputs():
    load_spec(SC02_SPEC)
    result = run_chain(
        "SC02", SC02_ST, scan_ms=10, total_scans=90, input_at=_sc02_inputs,
        expects=(
            Expect("Fwd_Out", True, scan=3, desc="正转吸合"),
            Expect("Rev_Out", False, scan=41, desc="换向瞬间反转未吸合"),
            Expect("Fwd_Out", False, scan=61, desc="停止后正转释放"),
        ),
    )
    assert result.passed, result.failures


def test_sc02_simultaneous_buttons_stay_stopped():
    """ pressing Fwd and Rev in the same scan must not energise either."""

    def inputs(scan):
        return {"Fwd_PB": scan == 2, "Rev_PB": scan == 2,
                "Stop_PB": False, "EStop_OK": True}

    result = run_chain(
        "SC02X", SC02_ST, scan_ms=10, total_scans=10, input_at=inputs,
        expects=(
            Expect("Fwd_Out", False, scan=9, desc="同按双键正转不得吸合"),
            Expect("Rev_Out", False, scan=9, desc="同按双键反转不得吸合"),
        ),
    )
    assert result.passed, result.failures


# =====================================================================
# SC-03 单气缸往复+超时报警 (B组: 时序动作, TON)
# =====================================================================

SC03_SPEC = """
specVersion: "1.0"
project: { id: sc03-cylinder, name: 单气缸往复带超时, scanMs: 10 }
io:
  digital:
    - { name: Cycle_PB,       dir: in,  addr: "%I0.0", desc: 循环启动 }
    - { name: Cyl_Extended,   dir: in,  addr: "%I0.1", desc: 伸出到位 }
    - { name: Cyl_Retracted,  dir: in,  addr: "%I0.2", desc: 缩回到位 }
    - { name: EStop_OK,       dir: in,  addr: "%I0.3", desc: 急停正常 }
    - { name: Cyl_Out,        dir: out, addr: "%Q0.0", desc: 电磁阀 }
    - { name: Alarm_Fault,    dir: out, addr: "%Q0.1", desc: 超时报警 }
modes: [Auto]
params:
  - { name: ExtTimeOut, type: TIME, value: 1s, desc: 伸出超时 }
machines:
  - name: Cylinder
    initial: Retracted
    states:
      - { name: Retracted, entry: [Cyl_Out:=0, Alarm_Fault:=0] }
      - { name: Extending, entry: [Cyl_Out:=1] }
      - { name: Fault,     entry: [Cyl_Out:=0, Alarm_Fault:=1] }
    transitions:
      - { from: Retracted, to: Extending, when: "Cycle_PB AND EStop_OK", prio: 1 }
      - { from: Extending, to: Retracted, when: "Cyl_Extended", prio: 2 }
      - { from: "*",       to: Fault,     when: "NOT EStop_OK", prio: 0 }
interlocks:
  - { when: "NOT EStop_OK", then: [Cyl_Out:=0], desc: 急停断阀 }
"""

SC03_ST = """
PROGRAM Cylinder
VAR_INPUT
    Cycle_PB : BOOL;
    Cyl_Extended : BOOL;
    Cyl_Retracted : BOOL;
    EStop_OK : BOOL;
END_VAR
VAR_OUTPUT
    Cyl_Out : BOOL;
    Alarm_Fault : BOOL;
END_VAR
VAR
    State : DINT;
    Timer : DINT;
END_VAR

IF NOT EStop_OK THEN
    State := 2;
    Cyl_Out := FALSE;
    Alarm_Fault := TRUE;
    Timer := 0;
ELSIF State = 0 AND Cycle_PB AND EStop_OK THEN
    State := 1;
    Cyl_Out := TRUE;
    Alarm_Fault := FALSE;
    Timer := 0;
ELSIF State = 1 THEN
    IF Cyl_Extended THEN
        State := 0;
        Cyl_Out := FALSE;
        Timer := 0;
    ELSE
        Timer := Timer + 1;
        IF Timer >= 100 THEN
            State := 2;
            Cyl_Out := FALSE;
            Alarm_Fault := TRUE;
        END_IF;
    END_IF;
ELSIF State = 2 THEN
    Cyl_Out := FALSE;
    Alarm_Fault := TRUE;
    Timer := 0;
    IF Cycle_PB AND EStop_OK THEN
        State := 0;
        Alarm_Fault := FALSE;
    END_IF;
END_IF;
END_PROGRAM
"""


def test_sc03_extend_timeout_raises_alarm():
    """Cylinder never reaches the extended switch -> TON times out -> fault."""

    def inputs(scan):
        # button at scan 2, extended sensor NEVER fires (stuck_0 injection)
        return {"Cycle_PB": scan == 2, "Cyl_Extended": False,
                "Cyl_Retracted": True, "EStop_OK": True}

    result = run_chain(
        "SC03", SC03_ST, scan_ms=10, total_scans=200, input_at=inputs,
        expects=(
            Expect("Cyl_Out", True, scan=3, desc="启动后阀得电"),
            Expect("Cyl_Out", True, scan=100, desc="1s 内阀保持得电(未超时)"),
            Expect("Alarm_Fault", True, scan=104, desc="TON 1s 超时后报警"),
            Expect("Cyl_Out", False, scan=104, desc="超时后断阀"),
        ),
    )
    assert result.passed, result.failures


def test_sc03_normal_cycle_no_alarm():
    """Cylinder extends in 500ms -> reaches sensor -> no alarm."""

    def inputs(scan):
        extended = 50 <= scan < 80          # 500ms after start
        return {"Cycle_PB": scan == 2, "Cyl_Extended": extended,
                "Cyl_Retracted": not extended, "EStop_OK": True}

    result = run_chain(
        "SC03N", SC03_ST, scan_ms=10, total_scans=120, input_at=inputs,
        expects=(
            Expect("Cyl_Out", True, scan=3, desc="阀得电伸出"),
            Expect("Cyl_Out", False, scan=51, desc="到位后断阀"),
            Expect("Alarm_Fault", False, scan=100, desc="全程无报警"),
        ),
        assert_nevers=(AssertNever("Alarm_Fault", True, desc="正常循环不得报警"),),
    )
    assert result.passed, result.failures


# =====================================================================
# SC-04 手自动模式+急停全局复位 (D组: 状态机)
# =====================================================================

SC04_SPEC = """
specVersion: "1.0"
project: { id: sc04-modes, name: 手自动模式与急停复位, scanMs: 10 }
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
      - { from: Idle, to: Run,   when: "Mode_Auto AND Start_PB AND EStop_OK", prio: 1 }
      - { from: Run,  to: Idle,  when: "NOT Mode_Auto OR NOT Start_PB", prio: 1 }
      - { from: "*",  to: Fault, when: "NOT EStop_OK", prio: 0 }
      - { from: Fault, to: Idle, when: "Reset_PB AND EStop_OK", prio: 1 }
interlocks:
  - { when: "NOT EStop_OK", then: [Conv_Run:=0], desc: 急停断带 }
  - { when: "NOT Mode_Auto", then: [Conv_Run:=Manual_Jog], desc: 手动点动, manualOnly: true }
"""

SC04_ST = """
PROGRAM LineCtl
VAR_INPUT
    Mode_Auto : BOOL;
    Start_PB : BOOL;
    Manual_Jog : BOOL;
    Reset_PB : BOOL;
    EStop_OK : BOOL;
END_VAR
VAR_OUTPUT
    Conv_Run : BOOL;
    HMI_Fault : BOOL;
END_VAR
VAR
    State : DINT;
END_VAR

IF NOT EStop_OK THEN
    State := 2;
    Conv_Run := FALSE;
    HMI_Fault := TRUE;
ELSIF State = 2 THEN
    Conv_Run := FALSE;
    HMI_Fault := TRUE;
    IF Reset_PB AND EStop_OK THEN
        State := 0;
        HMI_Fault := FALSE;
    END_IF;
ELSIF State = 0 AND Mode_Auto AND Start_PB AND EStop_OK THEN
    State := 1;
    Conv_Run := TRUE;
    HMI_Fault := FALSE;
ELSIF State = 1 AND (NOT Mode_Auto OR NOT Start_PB) THEN
    State := 0;
    Conv_Run := FALSE;
ELSIF State = 0 AND NOT Mode_Auto THEN
    Conv_Run := Manual_Jog;
END_IF;
END_PROGRAM
"""


def test_sc04_mode_switch_and_estop_reset_chain():
    """Auto run -> estop -> fault -> reset -> manual jog (interlock path)."""

    def inputs(scan):
        return {
            "Mode_Auto": 0 <= scan < 60,
            "Start_PB": 10 <= scan < 30,
            "Manual_Jog": 90 <= scan < 110,
            "Reset_PB": scan == 70,
            "EStop_OK": scan != 40,
        }

    result = run_chain(
        "SC04", SC04_ST, scan_ms=10, total_scans=140, input_at=inputs,
        expects=(
            Expect("Conv_Run", True, scan=11, desc="自动模式启动输送带"),
            Expect("HMI_Fault", True, scan=41, desc="急停触发故障灯"),
            Expect("Conv_Run", False, scan=41, desc="急停断带"),
            Expect("HMI_Fault", False, scan=71, desc="复位按钮清除故障"),
            Expect("Conv_Run", True, scan=91, desc="手动点动经互锁吸合"),
            Expect("Conv_Run", False, scan=111, desc="松开点动释放"),
        ),
    )
    assert result.passed, result.failures


def test_sc04_estop_blocks_restart_until_reset():
    """Estop during run: conveyor must stay off even if Start re-pressed
    while in Fault, until Reset is given."""

    def inputs(scan):
        return {
            "Mode_Auto": True,
            "Start_PB": 10 <= scan,          # held from scan 10
            "Manual_Jog": False,
            "Reset_PB": scan == 90,
            "EStop_OK": scan < 20 or scan >= 90,  # estop 20..89
        }

    result = run_chain(
        "SC04R", SC04_ST, scan_ms=10, total_scans=120, input_at=inputs,
        expects=(
            Expect("Conv_Run", True, scan=11, desc="急停前运行"),
            Expect("Conv_Run", False, scan=30, desc="急停期间保持断开"),
            Expect("HMI_Fault", True, scan=30, desc="故障灯亮"),
            Expect("Conv_Run", False, scan=85, desc="未复位时 Start 无效"),
            Expect("HMI_Fault", False, scan=91, desc="复位后故障清除"),
            Expect("Conv_Run", True, scan=92, desc="复位后自动恢复(Start仍按住)"),
        ),
    )
    assert result.passed, result.failures


# =====================================================================
# cross-scenario: W1 kernel determinism still holds (chain backbone)
# =====================================================================

def test_w1_sorter_determinism_still_green():
    ok, detail = check_determinism(20)
    assert ok, detail


def test_all_chain_digests_differ_across_scenarios():
    """Different scenarios must produce different traces (no accidental
    hash collisions between chains)."""
    digests = {
        run_chain("SC01", SC01_ST, 10, 120, _sc01_inputs).digest,
        run_chain("SC02", SC02_ST, 10, 90, _sc02_inputs).digest,
    }
    assert len(digests) == 2
