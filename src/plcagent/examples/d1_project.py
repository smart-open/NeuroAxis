"""D1 sample project (W4): sorter with plant components + DSL suite.

This is the canonical end-to-end reference: Spec -> generated ST -> plant
simulation -> DSL suite. The component->PLC bridge maps plant input ports
to program VAR_INPUTs (5.3 bind via io.addr; here by name).
"""

from __future__ import annotations

from plcagent.gen import render
from plcagent.plant import PlantSim
from plcagent.spec.loader import load_spec

D1_SPEC = """
specVersion: "1.0"
project: { id: d1-sorter, name: D1 sorter, scanMs: 10 }
io:
  digital:
    - { name: Start_PB,    dir: in,  addr: "%I0.0", desc: start }
    - { name: Stop_PB,     dir: in,  addr: "%I0.1", desc: stop }
    - { name: PE_SortPos,  dir: in,  addr: "%I0.2", desc: sort photoeye }
    - { name: Safety_OK,   dir: in,  addr: "%I0.3", desc: safety chain ok }
    - { name: Conv_Run,    dir: out, addr: "%Q0.0", desc: conveyor run }
    - { name: Push_Out,    dir: out, addr: "%Q0.1", desc: pusher valve }
    - { name: HMI_Fault,   dir: out, addr: "%Q0.2", desc: fault lamp }
modes: [Auto]
machines:
  - name: Sorter
    initial: Idle
    states:
      - { name: Idle,   entry: [Conv_Run:=0, Push_Out:=0, HMI_Fault:=0] }
      - { name: Move,   entry: [Conv_Run:=1, Push_Out:=0] }
      - { name: Push,   entry: [Push_Out:=1] }
      - { name: Fault,  entry: [Conv_Run:=0, Push_Out:=0, HMI_Fault:=1] }
    transitions:
      - { from: "*",    to: Fault, when: "NOT Safety_OK", prio: 0 }
      - { from: Idle,   to: Move,  when: "Start_PB AND Safety_OK", prio: 1 }
      - { from: Move,   to: Push,  when: "PE_SortPos", prio: 1 }
      - { from: Push,   to: Idle,  when: "Stop_PB OR NOT PE_SortPos", prio: 1 }
interlocks:
  - { when: "NOT Safety_OK", then: [Conv_Run:=0, Push_Out:=0], desc: safety cut }
"""

# plant <-> PLC bridge (the io.addr mapping): plant inputs -> program
# inputs, and program outputs -> plant output ports
BRIDGE = {
    "belt_pe_out": "PE_SortPos",
    "safety_safety_ok": "Safety_OK",
}

OUTPUT_BRIDGE = {
    "Conv_Run": "belt_motor_on",
    "Push_Out": None,          # pusher valve has no plant component in W4
}


def build_suite() -> dict:
    """The D1 DSL suite (5.4). Timing: conveyor 200mm/s, item reaches the
    sensor (~980mm) about 4900ms after push_item."""
    return {
        "suite": "d1-sorter",
        "cases": [
            {
                "id": "estop_immediate",
                "desc": "safety chain open: every output cuts immediately",
                "steps": [
                    {"set": {"Start_PB": False, "Safety_OK": False}},
                    {"expect": {"Conv_Run": False, "withinMs": 100}},
                    {"expect": {"HMI_Fault": True, "withinMs": 100}},
                ],
                "assert_never_all": ["Conv_Run AND NOT Safety_OK"],
            },
            {
                "id": "push_cycle",
                "desc": "normal sort: start -> item -> photoeye -> push",
                "steps": [
                    {"set": {"Safety_OK": True}},
                    {"set": {"Start_PB": True}},
                    {"expect": {"Conv_Run": True, "withinMs": 100}},
                    {"drive": "belt.push_item()"},
                    {"expect": {"PE_SortPos": True, "afterMs": 4700, "withinMs": 600}},
                    {"expect": {"Push_Out": True, "withinMs": 200}},
                    {"set": {"Start_PB": False}},
                ],
                "assert_never_all": ["Push_Out AND NOT Conv_Run"],
            },
        ],
    }


def d1_plant() -> PlantSim:
    """D1 plant layout: one conveyor + one safety circuit."""
    plant = PlantSim()
    plant.add("conveyor", "belt", {"length_mm": 1000, "speed_mm_s": 200.0})
    plant.add("safety_circuit", "safety")
    return plant


def d1_generated_st() -> str:
    """Generated ST for D1 (deterministic, SpecHash-stamped)."""
    return render(load_spec(D1_SPEC)).combined


def apply_bridge(plant: PlantSim) -> None:
    """Apply both bridge directions: plant inputs -> program inputs after
    physics, program outputs -> plant output ports after each scan."""
    for source, target in BRIDGE.items():
        if target in plant.direct_inputs:
            continue                 # DSL set/init wins over the bridge
        if source in plant.inputs:
            plant.inputs[target] = plant.inputs[source]
    for source, target in OUTPUT_BRIDGE.items():
        if target is not None and source in plant.outputs:
            plant.outputs[target] = plant.outputs[source]
