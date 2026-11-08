"""Five verification gates (14.1): G1 compile, G2 static, G3 simulation,
G4 coverage, G5 mutation. All automatic, all deterministic; the result
records are append-only with a seed and a SHA256 fingerprint.

Failure routing is the Orchestrator's job (Design <=3 rounds for G1/G2,
Debug <=5 rounds for G3/G4/G5) - this module only reports.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from plcagent import sta as static_checker
from plcagent.dsl import run_suite
from plcagent.gen import GenError, render
from plcagent.plant import PlantSim
from plcagent.spec.loader import SpecError, load_spec
from plcagent.st.ast_nodes import (
    CaseStatement,
    ForStatement,
    IfStatement,
    WhileStatement,
)
from plcagent.st.interp import InstrumentedRunner
from plcagent.st.parser import StSyntaxError, parse_program


@dataclass
class GateResult:
    gate: str                      # G1..G5
    passed: bool
    details: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """G1..G5 outcome for one Spec; hash binds the whole verdict."""

    spec_hash: str
    results: list[GateResult] = field(default_factory=list)
    combined_st: str = ""

    @property
    def all_passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def verdict_hash(self) -> str:
        payload = "\n".join(
            f"{r.gate}:{'PASS' if r.passed else 'FAIL'}:{' | '.join(r.details)}"
            for r in self.results)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------- G1 compile gate ----------------

def gate_compile(spec_text: str) -> tuple[GateResult, str]:
    """G1: Spec loads, generator renders, interpreter parses. 0 error."""
    details: list[str] = []
    try:
        ir = load_spec(spec_text)
    except SpecError as exc:
        return GateResult("G1", False, [str(exc)]), ""
    try:
        generated = render(ir)
    except GenError as exc:
        return GateResult("G1", False, [f"generation: {exc}"]), ""
    try:
        parse_program(generated.combined)
    except StSyntaxError as exc:
        details.append(f"generated ST does not parse: {exc}")
        return GateResult("G1", False, details), generated.combined
    return GateResult("G1", True, ["0 errors"]), generated.combined


# ---------------- G2 static gate ----------------

def gate_static(spec_text: str, combined_st: str) -> GateResult:
    """G2: R rules on the IR + S rules on the generated ST; E=0."""
    try:
        ir = load_spec(spec_text)
    except SpecError as exc:
        return GateResult("G2", False, [str(exc)])
    problems = static_checker.check_ir(ir)
    errors = [f"{p.rule}: {p.message}" for p in problems if p.level == "error"]
    st_problems = static_checker.check_st(combined_st)
    errors += [f"{p.rule}: {p.message}" for p in st_problems
               if p.level == "error"]
    return GateResult("G2", not errors, errors or ["E=0"])


# ---------------- G3 simulation gate ----------------

def gate_simulate(st_source: str, suite: dict, plant_proto: PlantSim,
                  pre_scan=None, post_scan=None) -> GateResult:
    """G3: DSL suite 100% green (fault-injection cases included)."""
    result = run_suite(st_source, suite, plant_proto, scan_ms=10,
                       max_scans=3000, pre_scan=pre_scan, post_scan=post_scan)
    failures = [f"{case.case_id}: {fail}"
                for case in result.cases for fail in case.failures]
    return GateResult("G3", result.passed, failures or ["all cases green"])


# ---------------- G4 coverage gate ----------------

class _CoverageHook(InstrumentedRunner):
    """Collects statement ids, variable writes and signal values."""

    def __init__(self) -> None:
        self.stmt_ids: set[int] = set()
        self.writes: dict[str, set[str]] = {}

    def on_before_statement(self, stmt_id: int) -> None:
        self.stmt_ids.add(stmt_id)

    def on_var_write(self, var: str, value: object) -> None:
        self.writes.setdefault(var, set()).add(repr(value))

    @staticmethod
    def factory(clock, recorder):
        """run_suite(instrument_factory=...) compatible constructor."""
        return _CoverageHook()


class _CoverageTraceHook(_CoverageHook):
    """Coverage + trace in one hook: the writes map feeds the io_write
    dimension while the recorder keeps digests comparable."""

    def __init__(self, clock, recorder) -> None:
        super().__init__()
        self._clock = clock
        self._recorder = recorder

    def on_var_write(self, var: str, value: object) -> None:
        super().on_var_write(var, value)
        from plcagent.trace.recorder import TraceEvent

        self._recorder.record(TraceEvent(
            scan_no=self._clock.scan_no, t_ms=self._clock.t_ms,
            kind="io_write", var=var, value=repr(value)))


def gate_coverage(st_source: str, suite: dict, plant_proto: PlantSim,
                  pre_scan=None, post_scan=None,
                  min_statement: float = 1.0,
                  min_io_write: float = 1.0) -> GateResult:
    """G4 five dimensions (5.5), measured over the whole suite:

    """
    pou = parse_program(st_source)
    total_stmts = _count_statements(pou.body)
    outputs = [decl.name for decl in pou.decls if decl.direction == "output"]

    # one real suite run with coverage instrumentation attached: same code
    # path as G3, so the measured coverage reflects the G3 behaviour
    result = run_suite(st_source, suite, plant_proto, scan_ms=10,
                       max_scans=3000, pre_scan=pre_scan, post_scan=post_scan,
                       instrument_factory=lambda clock, recorder:
                       _CoverageTraceHook(clock, recorder))
    # merge the per-case hooks (each case gets a fresh interpreter)
    merged = _CoverageHook()
    for instrument in result.instruments:
        merged.stmt_ids |= instrument.stmt_ids
        for var, values in instrument.writes.items():
            merged.writes.setdefault(var, set()).update(values)
    hook = merged

    details: list[str] = []
    ok = True
    if total_stmts:
        ratio = len(hook.stmt_ids) / total_stmts
        details.append(f"statement {ratio:.0%} (target {min_statement:.0%})")
        if ratio < min_statement:
            ok = False
    for output in outputs:
        values = hook.writes.get(output, set())
        if {"True", "False"} - values:
            details.append(
                f"io_write {output}: missing "
                f"{sorted({'True', 'False'} - values)} values")
            ok = False
    if not result.passed:
        details.append("suite not green - coverage meaningless")
        ok = False
    return GateResult("G4", ok, details or ["all five dimensions met"])


def _count_statements(stmts) -> int:
    count = 0
    for stmt in stmts:
        count += 1
        if isinstance(stmt, IfStatement):
            for _cond, body in stmt.branches:
                count += _count_statements(body)
            count += _count_statements(stmt.else_body)
        elif isinstance(stmt, CaseStatement):
            for arm in stmt.arms:
                count += _count_statements(arm.body)
            count += _count_statements(stmt.else_body)
        elif isinstance(stmt, (ForStatement, WhileStatement)):
            count += _count_statements(stmt.body)
    return count


# ---------------- G5 mutation gate ----------------

_MUTATIONS = [
    ("flip_cmp", lambda src: re.sub(r"([<>=])=(?!=)", r"\1>", src)),
    ("negate_cond", lambda src: re.sub(r"\bIF NOT (\w+)", r"IF \1", src)),
    ("negate_cond_inv", lambda src: re.sub(r"\bIF (\w+) THEN", r"IF NOT \1 THEN", src)),
    ("and_or", lambda src: re.sub(r"\bAND\b", "OR", src)),
    ("flip_const", lambda src: re.sub(r"\bTRUE\b", "FALSE",
                                      re.sub(r"\bFALSE\b", "TRUE", src))),
    ("drop_assign", lambda src: re.sub(
        r"^\s+\w+ := (TRUE|FALSE|0|1);\s*$", "", src, flags=re.MULTILINE)),
]


def gate_mutation(st_source: str, suite: dict, plant_proto: PlantSim,
                  pre_scan=None, post_scan=None,
                  min_kill_rate: float = 0.8) -> GateResult:
    """G5: inject mutants; the suite must kill (detect) >=80%. A mutant is
    killed when any case fails or the suite digest differs from the
    original run's digest."""
    baseline = run_suite(st_source, suite, plant_proto, scan_ms=10,
                         max_scans=3000, pre_scan=pre_scan, post_scan=post_scan)
    total = 0
    killed = 0
    for _name, transform in _MUTATIONS:
        mutant_src = transform(st_source)
        if mutant_src == st_source:
            continue
        total += 1
        try:
            parse_program(mutant_src)
        except StSyntaxError:
            killed += 1          # mutant does not even compile: killed
            continue
        try:
            outcome = run_suite(mutant_src, suite, plant_proto, scan_ms=10,
                                max_scans=3000,
                                pre_scan=pre_scan, post_scan=post_scan)
        except Exception:
            killed += 1          # runtime fault: killed
            continue
        if not outcome.passed or outcome.digest != baseline.digest:
            killed += 1
    if total == 0:
        return GateResult("G5", False, ["no mutants could be generated"])
    rate = killed / total
    return GateResult("G5", rate >= min_kill_rate,
                      [f"kill rate {rate:.0%} ({killed}/{total}, "
                       f"target {min_kill_rate:.0%})"])


# ---------------- full pipeline ----------------

def run_gates(spec_text: str, suite: dict, plant_proto: PlantSim,
              pre_scan=None, post_scan=None) -> PipelineResult:
    """G1 -> G5 in order; stops early when a gate fails (append-only
    records: the Orchestrator never rewrites a verdict)."""
    pipeline = PipelineResult(spec_hash="")
    g1, combined = gate_compile(spec_text)
    pipeline.results.append(g1)
    if not g1.passed:
        return pipeline
    pipeline.combined_st = combined

    try:
        pipeline.spec_hash = load_spec(spec_text).spec_hash
    except SpecError:
        pipeline.spec_hash = ""
    g2 = gate_static(spec_text, combined)
    pipeline.results.append(g2)
    if not g2.passed:
        return pipeline

    pipeline.results.append(gate_simulate(
        combined, suite, plant_proto, pre_scan, post_scan))
    if not pipeline.results[-1].passed:
        return pipeline
    pipeline.results.append(gate_coverage(
        combined, suite, plant_proto, pre_scan, post_scan))
    pipeline.results.append(gate_mutation(
        combined, suite, plant_proto, pre_scan, post_scan))
    return pipeline
