"""W4 tests: virtual plant library + test DSL runner (5.3/5.4)."""

from __future__ import annotations

import pytest

from plcagent.dsl import RunnerError, run_suite
from plcagent.plant import (
    ComponentRegistry,
    Cylinder,
    FaultSpec,
    PlantSim,
)

# ---------------- component registry ----------------

def test_registry_has_12_builtin_kinds():
    kinds = set(ComponentRegistry.kinds())
    assert {"motor", "conveyor", "cylinder", "photoelectric", "encoder",
            "pump", "switch_valve", "modulating_valve", "tank",
            "transmitter", "heater", "safety_circuit"} <= kinds


def test_registry_rejects_duplicate_kind():
    with pytest.raises(ValueError, match="already registered"):
        @ComponentRegistry.register("cylinder")
        class Duplicate(Cylinder):
            pass


def test_registry_rejects_unknown_params():
    with pytest.raises(ValueError, match="unknown params"):
        ComponentRegistry.create("cylinder", "c1", {"bogus": 1})


def test_unknown_kind_fails():
    with pytest.raises(ValueError, match="unknown component kind"):
        ComponentRegistry.create("unicorn", "u1")


# ---------------- component physics ----------------

def _sim(*specs):
    plant = PlantSim()
    for kind, name in specs:
        plant.add(kind, name)
    return plant


def test_cylinder_stroke_timing():
    plant = _sim(("cylinder", "cyl"))
    cyl = plant.get("cyl")
    plant.outputs["cyl_valve_out"] = True
    # stroke 2000ms: after 1000ms progress must be exactly 0.5
    plant.step_scan(1000)
    assert cyl.progress == pytest.approx(0.5)
    assert plant.inputs["cyl_extended"] is False
    plant.step_scan(1000)
    assert cyl.progress == pytest.approx(1.0)
    assert plant.inputs["cyl_extended"] is True
    assert plant.inputs["cyl_retracted"] is False


def test_cylinder_retracts_on_valve_off():
    plant = _sim(("cylinder", "cyl"))
    cyl = plant.get("cyl")
    plant.outputs["cyl_valve_out"] = True
    plant.step_scan(2000)
    plant.outputs["cyl_valve_out"] = False
    plant.step_scan(1000)
    assert cyl.progress == pytest.approx(0.5)
    assert plant.inputs["cyl_retracted"] is False


def test_conveyor_moves_items_and_sensor():
    plant = _sim(("conveyor", "conv"))
    conv = plant.get("conv")
    conv.drive("push_item", {})
    plant.outputs["conv_motor_on"] = True
    # speed 200mm/s: item travels 200mm per 1000ms; sensor at 980mm ±10
    plant.step_scan(4900)      # item at 980mm
    assert plant.inputs["conv_pe_out"] is True
    plant.step_scan(200)       # item at 1020mm -> filtered out (past end)
    assert plant.inputs["conv_pe_out"] is False
    assert conv.items == []


def test_tank_level_integration():
    plant = _sim(("tank", "tk"))
    plant.outputs["tk_in_flow"] = 2.0      # L/s
    plant.outputs["tk_out_flow"] = 0.5
    plant.step_scan(1000)                  # 1s: +1.5 / area 1.0
    assert plant.inputs["tk_level"] == pytest.approx(1.5, abs=1e-6)
    assert plant.inputs["tk_hi"] is False
    plant.outputs["tk_in_flow"] = 0.0
    plant.step_scan(5000)
    assert plant.inputs["tk_level"] == pytest.approx(0.0)   # clamped
    assert plant.inputs["tk_lo"] is True


def test_safety_circuit_estop():
    plant = _sim(("safety_circuit", "safety"))
    plant.step_scan(10)
    assert plant.inputs["safety_safety_ok"] is True
    plant.get("safety").drive("press_estop", {"value": False})
    plant.step_scan(10)
    assert plant.inputs["safety_safety_ok"] is False


def test_fault_injection_stuck_0():
    plant = _sim(("cylinder", "cyl"))
    plant.outputs["cyl_valve_out"] = True
    plant.inject("cyl", "extended", FaultSpec(kind="stuck_0"))
    plant.step_scan(2500)
    assert plant.inputs["cyl_extended"] is False     # stuck despite progress=1
    assert plant.get("cyl").progress == pytest.approx(1.0)


def test_pump_first_order_response():
    plant = _sim(("pump", "p1"))
    plant.outputs["p1_run"] = True
    plant.step_scan(100)                   # one tau: 63% of 100 L/min
    assert 50 < plant.inputs["p1_flow"] < 70


# ---------------- DSL runner ----------------

# signals set by the DSL must be the program's declared VAR_INPUTs
MOTOR_ST = """
PROGRAM Main
VAR_INPUT
    Start_PB : BOOL;
    Stop_PB : BOOL;
    Safety_OK : BOOL;
END_VAR
VAR_OUTPUT
    Motor_Run : BOOL;
END_VAR
IF NOT Safety_OK THEN
    Motor_Run := FALSE;
ELSIF Motor_Run AND Stop_PB THEN
    Motor_Run := FALSE;
ELSIF Start_PB AND NOT Motor_Run THEN
    Motor_Run := TRUE;
END_IF;
END_PROGRAM
"""


def _motor_plant():
    plant = PlantSim()
    plant.add("motor", "motor")
    plant.add("safety_circuit", "safety")
    # PLC var Motor_Run mirrors into the plant's motor run input via suite
    return plant


def test_dsl_motor_start_stop_case():
    suite = {
        "suite": "motor-smoke",
        "cases": [{
            "id": "start_stop",
            "init": {"Safety_OK": True},
            "steps": [
                {"set": {"Start_PB": True}},
                {"expect": {"Motor_Run": True, "withinMs": 100}},
                {"set": {"Start_PB": False}},
            ],
        }],
    }
    plant = _motor_plant()
    # bridge: PLC output drives plant motor input
    result = run_suite(
        MOTOR_ST, suite, plant, scan_ms=10,
        max_scans=1000) if False else None
    # note: set only drives plant inputs; Motor_Run is a PLC output, so the
    # expect must observe the PLC variable - SignalView supports both.
    result = run_suite(MOTOR_ST, suite, plant, scan_ms=10, max_scans=1000)
    assert result.passed, [c.failures for c in result.cases]


def test_dsl_expect_window_expiry_fails():
    suite = {
        "suite": "window",
        "cases": [{
            "id": "never_true",
            "steps": [
                {"expect": {"Motor_Run": True, "afterMs": 50, "withinMs": 100}},
            ],
        }],
    }
    with pytest.raises(RunnerError, match="not met within"):
        run_suite(MOTOR_ST, suite, _motor_plant(), scan_ms=10, max_scans=1000)


def test_dsl_assert_never_violation_detected():
    """A naive program (no safety guard) keeps running after Safety_OK
    drops - the whole-case invariant must catch it."""
    naive_st = """
PROGRAM Main
VAR_INPUT
    Start_PB : BOOL;
    Safety_OK : BOOL;
END_VAR
VAR_OUTPUT
    Motor_Run : BOOL;
END_VAR
IF Start_PB THEN
    Motor_Run := TRUE;
END_IF;
END_PROGRAM
"""
    suite = {
        "suite": "never",
        "cases": [{
            "id": "estop_violation",
            "init": {"Safety_OK": True},
            "steps": [
                {"set": {"Start_PB": True}},
                {"expect": {"Motor_Run": True, "withinMs": 100}},
                {"set": {"Safety_OK": False}},
            ],
            "assert_never_all": ["Safety_OK AND Motor_Run"],
        }],
    }
    result = run_suite(naive_st, suite, _motor_plant(), scan_ms=10,
                       max_scans=2000)
    assert not result.passed
    assert any("invariant violated" in failure
               for failure in result.cases[0].failures)


def test_dsl_drive_and_unknown_component():
    suite = {
        "suite": "drive",
        "cases": [{
            "id": "push",
            "steps": [
                {"drive": "belt.push_item()"},
                {"expect": {"belt_pe_out": False, "withinMs": 100}},
            ],
        }],
    }
    plant = PlantSim()
    plant.add("conveyor", "belt")
    result = run_suite("PROGRAM Main END_PROGRAM", suite, plant, scan_ms=10)
    assert result.passed, [c.failures for c in result.cases]

    bad = {
        "suite": "drive-bad",
        "cases": [{"id": "x", "steps": [{"drive": "ghost.push_item()"}]}],
    }
    with pytest.raises(ValueError, match="no plant component"):
        run_suite("PROGRAM Main END_PROGRAM", bad, plant, scan_ms=10)


def test_dsl_set_rejects_non_input_signal():
    suite = {
        "suite": "set-guard",
        "cases": [{"id": "x", "steps": [{"set": {"Motor_Run": True}}]}],
    }
    with pytest.raises(RunnerError, match="reject unknown signals"):
        run_suite(MOTOR_ST, suite, _motor_plant(), scan_ms=10)


def test_dsl_deterministic_digest():
    suite = {
        "suite": "det",
        "cases": [{
            "id": "run",
            "init": {"Safety_OK": True},
            "steps": [
                {"set": {"Start_PB": True}},
                {"expect": {"Motor_Run": True, "withinMs": 100}},
            ],
        }],
    }
    digests = set()
    for _ in range(3):
        result = run_suite(MOTOR_ST, suite, _motor_plant(), scan_ms=10,
                           max_scans=1000)
        digests.add(result.digest)
    assert len(digests) == 1
