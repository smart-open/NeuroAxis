"""Core 8 tool contracts (4.3): strongly typed, idempotent, auditable.

Each tool wraps an existing deterministic core (spec/loader, gen, sta,
dsl). None of them mutates global state; sim.run is only invoked by the
Orchestrator (4.1 permission matrix, hardcoded).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from plcagent import sta as static_checker
from plcagent.dsl import RunnerError, run_suite
from plcagent.gen import GenError, render
from plcagent.plant import PlantSim
from plcagent.spec.loader import SpecError, load_spec
from plcagent.spec.validator import Problem, validate


class ToolContext(BaseModel):
    """Who is calling, with which permission (4.1 matrix)."""

    run_id: str
    role: str                      # orchestrator / debugger / designer / ...
    perm: str = "read"             # read / write_spec / run_sim / export


class ToolOutput(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------- spec.validate ----------------

class SpecValidateIn(BaseModel):
    spec_text: str


class SpecValidateOut(ToolOutput):
    spec_hash: str = ""


def spec_validate(spec_text: str, ctx: ToolContext) -> SpecValidateOut:
    """Full Spec gate: schema + V rules; errors carry rule codes."""
    del ctx  # read-only tool: no permission gate needed beyond existence
    try:
        project = load_spec(spec_text)
    except SpecError as exc:
        return SpecValidateOut(ok=False, errors=str(exc).splitlines())
    return SpecValidateOut(ok=True, spec_hash=project.spec_hash)


# ---------------- ir.check ----------------

class IrCheckIn(BaseModel):
    spec_text: str


class IrCheckOut(ToolOutput):
    spec_hash: str = ""


def ir_check(spec_text: str, ctx: ToolContext) -> IrCheckOut:
    """V-rule check on the built IR (semantic layer of 3.3)."""
    del ctx
    try:
        project = load_spec(spec_text)
    except SpecError as exc:
        return IrCheckOut(ok=False, errors=str(exc).splitlines())
    problems = validate(project)
    errors = [f"{p.code}: {p.message}" for p in problems if p.level == "error"]
    warnings = [f"{p.code}: {p.message}" for p in problems if p.level != "error"]
    return IrCheckOut(ok=not errors, errors=errors, warnings=warnings,
                      spec_hash=project.spec_hash)


# ---------------- gen.render ----------------

class GenRenderIn(BaseModel):
    spec_text: str


class GenRenderOut(ToolOutput):
    files: dict[str, str] = Field(default_factory=dict)
    combined: str = ""
    spec_hash: str = ""


def gen_render(spec_text: str, ctx: ToolContext) -> GenRenderOut:
    """Deterministic IR -> ST; pure function of the Spec text."""
    del ctx
    try:
        project = load_spec(spec_text)
        result = render(project)
    except (SpecError, GenError) as exc:
        return GenRenderOut(ok=False, errors=[str(exc)])
    return GenRenderOut(ok=True, files=result.files,
                        combined=result.combined, spec_hash=project.spec_hash)


# ---------------- sta.check ----------------

class StaCheckIn(BaseModel):
    st_source: str


def sta_check(st_source: str, ctx: ToolContext) -> ToolOutput:
    """S rules on ST source (13.1~13.3 first batch)."""
    del ctx
    problems = static_checker.check_st(st_source)
    errors = [f"{p.rule}: {p.message}" for p in problems if p.level == "error"]
    warnings = [f"{p.rule}: {p.message}" for p in problems if p.level != "error"]
    return ToolOutput(ok=not errors, errors=errors, warnings=warnings)


# ---------------- sim.run ----------------

class SimRunIn(BaseModel):
    st_source: str
    suite: dict
    plant: PlantSim
    scan_ms: int = 10
    max_scans: int = 100000
    post_scan: object | None = None   # callable(plant): plant<->PLC bridge

    model_config = {"arbitrary_types_allowed": True}


class SimRunOut(ToolOutput):
    digest: str = ""
    case_results: list[dict] = Field(default_factory=list)


def sim_run(spec: SimRunIn, ctx: ToolContext) -> SimRunOut:
    """Run the DSL suite. Permission gate: only run_sim may call this -
    the Orchestrator triggers simulations, never the roles themselves."""
    if ctx.perm != "run_sim":
        return SimRunOut(ok=False, errors=[
            f"role {ctx.role!r} lacks run_sim permission (4.1: simulation "
            f"is Orchestrator-triggered only)"])
    # an expect window that expires raises instead of failing soft; report
    # it as a normal failed case so the Debugger can attribute it
    try:
        result = run_suite(spec.st_source, spec.suite, spec.plant,
                           spec.scan_ms, spec.max_scans,
                           post_scan=spec.post_scan)
    except RunnerError as exc:
        return SimRunOut(ok=False, errors=[str(exc)])
    case_results = [{"case_id": c.case_id, "passed": c.passed,
                     "failures": c.failures} for c in result.cases]
    return SimRunOut(ok=result.passed, digest=result.digest,
                     case_results=case_results,
                     errors=[f for c in result.cases for f in c.failures])


# ---------------- trace.summarize ----------------

class SignalEvent(BaseModel):
    scan: int
    signal: str
    value: str


class TraceSummary(BaseModel):
    """Debugger's eyes on the trace (4.3) - not the raw trace."""

    failing_assertion: str = ""
    fail_scan: int = -1
    window_events: list[SignalEvent] = Field(default_factory=list)
    active_states: list[str] = Field(default_factory=list)
    suspicion_hints: list[str] = Field(default_factory=list)


def trace_summarize(case_failures: list[str], case_id: str,
                    timelines: dict[str, dict[int, str]] | None = None,
                    window_scans: int = 200) -> TraceSummary:
    """Compact the failure into a token-bounded summary: the failing
    assertion plus signal flips within the window before the failure."""
    failing = case_failures[0] if case_failures else "no failure recorded"
    fail_scan = -1
    for text in case_failures:
        if " at scan " in text:
            try:
                fail_scan = int(text.split(" at scan ")[1].split(")")[0]
                                .split(" ")[0])
                break
            except (IndexError, ValueError):
                continue
    events: list[SignalEvent] = []
    if timelines and fail_scan >= 0:
        window_start = max(0, fail_scan - window_scans)
        for signal, series in sorted(timelines.items()):
            for scan, value in sorted(series.items()):
                if window_start <= scan <= fail_scan:
                    events.append(SignalEvent(scan=scan, signal=signal,
                                              value=value))
    return TraceSummary(failing_assertion=f"[{case_id}] {failing}",
                        fail_scan=fail_scan, window_events=events)


# ---------------- ir.patch ----------------

class IrPatchProposal(BaseModel):
    """A Spec change proposal: human-visible, human-rejectable (4.3)."""

    case_id: str
    reason: str
    old_expr: str
    new_expr: str
    target: str = ""               # transition/interlock reference
    source: str = "rule_engine"    # rule_engine / llm


__all__ = [
    "Problem", "ToolContext", "ToolOutput",
    "SpecValidateIn", "SpecValidateOut", "spec_validate",
    "IrCheckIn", "IrCheckOut", "ir_check",
    "GenRenderIn", "GenRenderOut", "gen_render",
    "StaCheckIn", "sta_check",
    "SimRunIn", "SimRunOut", "sim_run",
    "SignalEvent", "TraceSummary", "trace_summarize",
    "IrPatchProposal",
]
