"""plcagent verify - determinism check (acceptance A2).

Runs the sample scenario N times and requires the trace digest to be
byte-identical across runs. Exit 0 = green, 2 = violation.
"""

from __future__ import annotations

from plcagent.examples import sorter
from plcagent.st.interp import InstrumentedRunner, Interpreter
from plcagent.st.parser import parse_program
from plcagent.trace.clock import VirtualClock
from plcagent.trace.recorder import TraceEvent, TraceRecorder


class TraceHook(InstrumentedRunner):
    """Records every output write as an io_write trace event."""

    def __init__(self, clock: VirtualClock, recorder: TraceRecorder) -> None:
        self._clock = clock
        self._recorder = recorder

    def on_var_write(self, var: str, value: object) -> None:
        self._recorder.record(TraceEvent(
            scan_no=self._clock.scan_no, t_ms=self._clock.t_ms,
            kind="io_write", var=var, value=repr(value)))


def run_scenario(inputs: list[dict[str, bool]] | None = None) -> tuple[str, TraceRecorder]:
    """Run the sorter scenario once; returns (trace digest, recorder)."""
    inputs = inputs if inputs is not None else sorter.scenario_inputs()
    clock = VirtualClock(scan_ms=sorter.SCAN_MS)
    recorder = TraceRecorder()
    interp = Interpreter(parse_program(sorter.SAMPLE_ST), clock, TraceHook(clock, recorder))
    for scan_inputs in inputs:
        interp.run_scan(scan_inputs)
    return recorder.digest(), recorder


def run_once() -> str:
    digest, _ = run_scenario()
    return digest


def check_determinism(runs: int = 50) -> tuple[bool, str]:
    """Run the scenario `runs` times; all digests must be identical."""
    digests = {run_once() for _ in range(runs)}
    if len(digests) == 1:
        return True, next(iter(digests))
    return False, f"{len(digests)} distinct digests across {runs} runs"
