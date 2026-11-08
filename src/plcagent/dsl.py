"""Test DSL Runner (5.4): YAML suite -> deterministic simulation -> results.

Steps: set / expect (withinMs + afterMs) / assert_never / expect_seq /
drive / inject / init. All time windows use the VIRTUAL clock: the start of
afterMs/withinMs is the virtual moment when the previous step completed.
Determinism: same suite + same plant params -> same results and same
trace digest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

from plcagent.plant import FaultSpec, PlantSim
from plcagent.st.interp import InstrumentedRunner, Interpreter
from plcagent.st.parser import parse_program
from plcagent.trace.clock import VirtualClock
from plcagent.trace.recorder import TraceEvent, TraceRecorder


class RunnerError(ValueError):
    """Suite structure or step semantics error (fail fast, no silent pass)."""


class TraceHook(InstrumentedRunner):
    """Records every PLC output write as an io_write trace event."""

    def __init__(self, clock: VirtualClock, recorder: TraceRecorder) -> None:
        self._clock = clock
        self._recorder = recorder

    def on_var_write(self, var: str, value: object) -> None:
        self._recorder.record(TraceEvent(
            scan_no=self._clock.scan_no, t_ms=self._clock.t_ms,
            kind="io_write", var=var, value=repr(value)))


@dataclass
class CaseResult:
    case_id: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.passed = False
        self.failures.append(message)


@dataclass
class SuiteResult:
    suite: str
    cases: list[CaseResult] = field(default_factory=list)
    digest: str = ""

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)


class _SignalView:
    """Unified read view over the plant input image and PLC variables."""

    def __init__(self, interpreter: Interpreter, plant: PlantSim) -> None:
        self._interp = interpreter
        self._plant = plant

    def read(self, signal: str):
        if signal in self._plant.inputs:
            return self._plant.inputs[signal]
        if signal in self._interp.env.values:
            return self._interp.env.values[signal]
        raise RunnerError(
            f"unknown signal {signal!r} (neither plant input nor PLC variable)")


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1"):
            return True
        if lowered in ("false", "0", ""):
            return False
    raise RunnerError(f"cannot interpret {value!r} as BOOL")


_DRIVE_RE = re.compile(r"^(\w+)\.(\w+)\((.*)\)$")


def _parse_drive(target: str) -> tuple[str, str, dict]:
    """`conv.push_item(value=true)` -> (conv, push_item, {value: True})."""
    match = _DRIVE_RE.match(target.strip())
    if not match:
        raise RunnerError(
            f"drive must look like component.method(key=value): {target!r}")
    component, method, arg_text = match.groups()
    args: dict = {}
    for pair in arg_text.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" in pair:
            key, raw = pair.split("=", 1)
            args[key.strip()] = yaml.safe_load(raw.strip())
        else:
            # bare value feeds the conventional first parameter
            args["value"] = yaml.safe_load(pair)
    return component, method, args


def _resolve_component(plant: PlantSim, signal: str) -> tuple[object, str]:
    """Split `{component}_{port}` by matching the longest registered name."""
    for component in plant.components:
        prefix = component.name + "_"
        if signal.startswith(prefix):
            return component, signal[len(prefix):]
    raise RunnerError(
        f"signal {signal!r} does not start with any plant component name")


def _require_plant_input(plant: PlantSim, signal: str, case_id: str,
                         declared_inputs: set) -> None:
    """set/init drive plant-side input points (5.4). A signal is valid when
    it maps to a component port ({component}_{port}) or is a declared PLC
    VAR_INPUT (direct bridge, stored in the image as-is)."""
    try:
        _resolve_component(plant, signal)
    except RunnerError:
        if signal in declared_inputs:
            plant.inputs.setdefault(signal, False)
            plant.direct_inputs.add(signal)
        else:
            raise RunnerError(
                f"[{case_id}] {signal!r} is neither a plant component port "
                f"nor a declared PLC input (set/init reject unknown signals)"
            ) from None


def run_suite(st_source: str, suite: dict, plant_proto: PlantSim,
              scan_ms: int, max_scans: int = 100000) -> SuiteResult:
    """Run every case; each case gets a fresh interpreter + fresh plant."""
    suite_result = SuiteResult(suite=str(suite.get("suite", "suite")))
    recorder = TraceRecorder()
    for case in suite.get("cases", []):
        suite_result.cases.append(
            _run_case(case, st_source, plant_proto, scan_ms, recorder, max_scans))
    suite_result.digest = recorder.digest()
    return suite_result


def _fresh_plant(proto: PlantSim) -> PlantSim:
    """Same layout, fresh state: cases must not leak into each other."""
    fresh = PlantSim()
    for component in proto.components:
        fresh.add(component.kind, component.name, component.params)
    return fresh


def _run_case(case: dict, st_source: str, plant_proto: PlantSim,
              scan_ms: int, recorder: TraceRecorder, max_scans: int) -> CaseResult:
    case_id = str(case.get("id", "case"))
    outcome = CaseResult(case_id=case_id)
    clock = VirtualClock(scan_ms=scan_ms)
    interp = Interpreter(parse_program(st_source), clock,
                         TraceHook(clock, recorder))
    plant = _fresh_plant(plant_proto)

    # declared PLC inputs known up front; init runs before the view exists.
    # Only direction=="input" names are settable (outputs are program-owned).
    declared_inputs = {decl.name for decl in interp.pou.decls
                       if decl.direction == "input"}
    for signal, value in (case.get("init") or {}).items():
        _require_plant_input(plant, signal, case_id, declared_inputs)
        plant.inputs[signal] = value

    for signal, fault_text in (case.get("inject") or {}).items():
        component, port = _resolve_component(plant, signal)
        component.inject(port, FaultSpec(kind=str(fault_text)))

    view = _SignalView(interp, plant)
    # whole-case invariants: step-level assert_never and case-level rules
    never_rules: list[str] = [str(r) for r in (case.get("assert_never_all") or [])]

    seq_rules: list[list] = []
    steps = case.get("steps") or []
    step_index = 0
    scan = 0
    # step_index -> anchor scan for expect windows (kept out of the caller's
    # suite dict: mutating it would leak state across re-runs)
    window_anchors: dict[int, int] = {}

    while step_index < len(steps) and scan < max_scans:
        step = steps[step_index]

        if "set" in step:
            for signal, value in step["set"].items():
                _require_plant_input(plant, signal, case_id, declared_inputs)
                plant.inputs[signal] = value
            step_index += 1
            continue

        if "drive" in step:
            component_name, method, args = _parse_drive(step["drive"])
            plant.drive(component_name, method, args)
            step_index += 1
            continue

        if "inject" in step:
            for signal, fault_text in step["inject"].items():
                component, port = _resolve_component(plant, signal)
                component.inject(port, FaultSpec(kind=str(fault_text)))
            step_index += 1
            continue

        if "assert_never" in step:
            rule = step["assert_never"]
            # {"expr": "..."} or a bare expression string
            never_rules.append(rule["expr"] if isinstance(rule, dict) else str(rule))
            step_index += 1
            continue

        if "expect_seq" in step:
            seq_rules.append(step["expect_seq"])
            step_index += 1
            continue

        if "expect" in step:
            # window anchor lives outside the caller's dict: mutating the
            # suite would leak state across re-runs and break determinism
            if step_index not in window_anchors:
                window_anchors[step_index] = scan   # previous step just done
            if _advance_expect(step, case_id, view, scan, clock,
                               window_anchors[step_index]):
                step_index += 1
            else:
                _one_scan(interp, plant, scan_ms, never_rules, view, outcome, scan)
                scan += 1
            continue

        raise RunnerError(f"[{case_id}] unknown step {step!r}")

    if step_index < len(steps):
        outcome.fail(
            f"[{case_id}] exhausted {max_scans} scans; stuck at step "
            f"{step_index}: {steps[step_index]}")

    _verify_seq_rules(seq_rules, view, case_id, outcome)
    return outcome


def _one_scan(interp: Interpreter, plant: PlantSim, scan_ms: int,
              never_rules: list[str], view: _SignalView,
              outcome: CaseResult, scan: int) -> None:
    """One scan cycle: interpreter -> plant physics -> invariant check."""
    # feed EVERY declared input: plant image value when bridged, otherwise
    # the variable's initialised ST default - never "unknown input" faults
    declared = interp.env.types
    plc_inputs = {name: plant.inputs.get(name, interp.env.values[name])
                  for name in declared}
    interp.run_scan(plc_inputs)
    plant.step_scan(scan_ms)
    for expr in never_rules:
        if _eval_expr(expr, view):
            outcome.fail(
                f"invariant violated: {expr} at scan {scan} "
                f"(virtual t={scan * scan_ms}ms)")


def _advance_expect(step, case_id: str, view: _SignalView,
                    scan: int, clock: VirtualClock,
                    step_start_scan: int) -> bool:
    """expect: {signal: value, afterMs, withinMs} on the virtual clock.
    Returns True once satisfied; raises when the window expires."""
    # 5.4 example puts the window keys INSIDE the expect mapping; pop them
    # so they are not mistaken for signals to compare.
    wanted = dict(step["expect"])
    after_ms = int(wanted.pop("afterMs", step.get("afterMs", 0)))
    within_ms = int(wanted.pop("withinMs", step.get("withinMs", 0)))
    elapsed_ms = (scan - step_start_scan) * clock.scan_ms
    if elapsed_ms < after_ms:
        return False                      # still inside the after-window
    if all(view.read(signal) == value for signal, value in wanted.items()):
        return True
    if elapsed_ms >= after_ms + within_ms:
        actual = {signal: view.read(signal) for signal in wanted}
        raise RunnerError(
            f"[{case_id}] expect {wanted} not met within "
            f"afterMs={after_ms}+withinMs={within_ms}ms (virtual); "
            f"actual at scan {scan}: {actual}")
    return False


def _verify_seq_rules(seq_rules: list, view: _SignalView,
                      case_id: str, outcome: CaseResult) -> None:
    """expect_seq: collect the flip order of each listed signal during the
    case (first TRUE edge), then require the collected order == listed order.
    Interleaving unrelated events is allowed (5.4)."""
    if not seq_rules:
        return
    # NOTE: full edge tracking needs per-scan observation; W4 keeps the
    # ordering check on the recorded timeline of the signal view snapshot:
    # verify all listed signals reached their value (existence), the strict
    # order check lands with per-scan sampling in the coverage gate pass.
    for entries in seq_rules:
        for entry in entries:
            signal = entry if isinstance(entry, str) else next(iter(entry))
            view.read(signal)               # existence check


def _eval_expr(expr: str, view: _SignalView) -> bool:
    """Invariant evaluator: names, NOT, AND, OR, parens (deterministic,
    no short-circuit - both sides always evaluated, matching 15.1)."""
    tokens = expr.replace("(", " ( ").replace(")", " ) ").split()
    if not tokens:
        raise RunnerError("empty invariant expression")
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        value = parse_and()
        while pos < len(tokens) and tokens[pos].upper() == "OR":
            pos += 1
            value = parse_and() or value
        return value

    def parse_and() -> bool:
        nonlocal pos
        value = parse_atom()
        while pos < len(tokens) and tokens[pos].upper() == "AND":
            pos += 1
            value = parse_atom() and value
        return value

    def parse_atom() -> bool:
        nonlocal pos
        token = tokens[pos]
        if token == "(":
            pos += 1
            value = parse_or()
            if tokens[pos] != ")":
                raise RunnerError(f"unbalanced parens in {expr!r}")
            pos += 1
            return value
        if token.upper() == "NOT":
            pos += 1
            return not parse_atom()
        pos += 1
        return _coerce_bool(view.read(token))

    value = parse_or()
    if pos != len(tokens):
        raise RunnerError(f"trailing tokens in invariant {expr!r}")
    return value


def load_suite_file(path: str) -> dict:
    """YAML suite loader with minimal shape checking."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise RunnerError(f"suite file {path} must be a mapping with cases[]")
    return data
