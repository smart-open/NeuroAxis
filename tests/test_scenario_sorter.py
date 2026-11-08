"""Functional self-test: D1 sorter scenario behaviour (task 4)."""

from plcagent.examples import sorter
from plcagent.verify import run_scenario


def _outputs(recorder):
    result: dict[str, dict[int, str]] = {}
    for event in recorder.events:
        if event.kind == "io_write":
            result.setdefault(event.var, {})[event.scan_no] = event.value
    return result


def test_start_pulse_turns_conveyor_on():
    _, recorder = run_scenario()
    conv = _outputs(recorder)["Conv"]
    assert conv[1] == "True"   # Start pulse at scan 0 -> conveyor at scan 1


def test_pe_triggers_push_then_releases():
    _, recorder = run_scenario()
    push = _outputs(recorder)["Push"]
    assert push[21] == "True"   # PE covered at scan 20, push at 21
    # Second cycle pushes at 61: scan 40 carries EStop=False AND phase==0, so
    # the state machine latches through; the next full idle->run cycle
    # completes at 60 (PE at 60..64 latches state 2 within the same scan).
    assert push[61] == "True"


def test_estop_forces_everything_off():
    _, recorder = run_scenario()
    conv = _outputs(recorder)["Conv"]
    assert conv[100] == "False"  # EStop at scan 100 -> interlock off
    # no further Conv writes until the next Start (outputs stay off)
    assert all(scan < 100 or value == "False" for scan, value in conv.items()
               if scan >= 100)


def test_scenario_is_deterministic():
    inputs = sorter.scenario_inputs()
    digests = {run_scenario(inputs)[0] for _ in range(5)}
    assert len(digests) == 1
