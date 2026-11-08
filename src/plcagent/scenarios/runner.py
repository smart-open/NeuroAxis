"""Scenario chain runner (5.4 mini-DSL).

Executes a scripted input sequence against a ST program on the virtual
clock, then evaluates expect/assert_never assertions over the trace.
Everything is deterministic: the whole chain is a pure function of the
scenario definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class Expect:
    signal: str
    value: bool
    scan: int                       # exact scan at which the value must hold
    desc: str = ""


@dataclass(frozen=True)
class AssertNever:
    signal: str
    value: bool
    desc: str = ""                  # signal must NEVER take this value


@dataclass
class ScenarioResult:
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    digest: str = ""

    def fail(self, message: str) -> None:
        self.passed = False
        self.failures.append(message)


def run_chain(name: str, st_source: str, scan_ms: int, total_scans: int,
              input_at, expects=(), assert_nevers=()) -> ScenarioResult:
    """Run one scenario chain and evaluate its assertions.

    input_at: callable scan_no -> {signal: value} for inputs this scan.
    """
    result = ScenarioResult()
    clock = VirtualClock(scan_ms=scan_ms)
    recorder = TraceRecorder()
    interp = Interpreter(parse_program(st_source), clock, TraceHook(clock, recorder))

    input_log: list[dict] = []
    for scan in range(total_scans):
        inputs = input_at(scan)
        input_log.append(dict(inputs))
        interp.run_scan(inputs)

    result.digest = recorder.digest()

    # build per-variable value timelines from io_write events; the last
    # known value carries forward across scans without a write (outputs
    # hold their value between assignments in a scan-based program).
    # A variable never written reads as its IEC default (FALSE / 0).
    timelines: dict[str, dict[int, str]] = {}
    for event in recorder.events:
        if event.kind == "io_write":
            timelines.setdefault(event.var, {})[event.scan_no] = event.value

    def value_at(signal: str, scan: int) -> str:
        """Last known value of signal at or before `scan`."""
        series = timelines.get(signal, {})
        for candidate in range(scan, -1, -1):
            if candidate in series:
                return series[candidate]
        return repr(False)  # IEC 61131-3 default for BOOL outputs

    for expect in expects:
        actual = value_at(expect.signal, expect.scan)
        wanted = repr(expect.value)
        if actual != wanted:
            result.fail(
                f"[{name}] expect {expect.signal}={expect.value} at scan {expect.scan}"
                f" ({expect.desc or ''}) but last write was {actual}")

    for rule in assert_nevers:
        series = timelines.get(rule.signal, {})
        for scan, value in sorted(series.items()):
            if value == repr(rule.value):
                result.fail(
                    f"[{name}] assert_never violated: {rule.signal}={rule.value}"
                    f" at scan {scan} ({rule.desc or ''})")
                break

    return result
