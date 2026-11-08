"""Orchestrator state machine (4.2): the only component that runs sims.

States: Intake -> Clarify -> Gate_Spec -> Design -> StaticCheck(<=3) ->
Simulate -> (Debug(<=5) | Gate_Result) -> Export | Escalate.

The permission matrix is hardcoded here (4.1): only the Debugger role may
issue Spec patch proposals, and no role except the Orchestrator carries
the run_sim permission - Prompts cannot change this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plcagent.agent.debugger import Diagnosis, attribute_failure
from plcagent.agent.tools import (
    SimRunIn,
    ToolContext,
    gen_render,
    ir_check,
    sim_run,
    sta_check,
    trace_summarize,
)
from plcagent.plant import PlantSim


class OrchestratorError(RuntimeError):
    """Illegal transition / budget exhausted / gate misuse."""


@dataclass
class RoundLog:
    state: str
    detail: str


@dataclass
class RunState:
    """All state for one run; resumable (4.2: rounds land in storage)."""

    run_id: str
    spec_text: str
    suite: dict
    plant_proto: PlantSim
    bridge: object | None = None      # callable(interp, plant): scan bridge
    state: str = "Intake"
    design_rounds: int = 0
    debug_rounds: int = 0
    max_design_rounds: int = 3
    max_debug_rounds: int = 5
    combined_st: str = ""
    diagnoses: list[Diagnosis] = field(default_factory=list)
    log: list[RoundLog] = field(default_factory=list)
    finished: bool = False
    escalated: bool = False

    def _log(self, state: str, detail: str) -> None:
        self.log.append(RoundLog(state=state, detail=detail))


class Orchestrator:
    """Drives one run through the pipeline. Gates are explicit method calls
    from the human (or the P0 self-approval stub)."""

    def __init__(self, run: RunState) -> None:
        self.run = run

    # -- pipeline steps ------------------------------------------------------

    def start(self) -> None:
        if self.run.state != "Intake":
            raise OrchestratorError(f"start from {self.run.state} is illegal")
        self.run._log("Intake", "materials accepted")
        self.run.state = "Clarify"

    def submit_spec(self, spec_text: str) -> dict:
        """Clarify done: validate the Spec draft (schema + V rules)."""
        if self.run.state not in ("Clarify", "Debug"):
            raise OrchestratorError(
                f"submit_spec from {self.run.state} is illegal")
        self.run.spec_text = spec_text
        ctx = ToolContext(run_id=self.run.run_id, role="orchestrator")
        result = ir_check(spec_text, ctx)
        self.run._log("Clarify",
                      "spec ok" if result.ok else f"spec errors: {result.errors}")
        self.run.state = "Gate_Spec"
        return {"ok": result.ok, "errors": result.errors,
                "warnings": result.warnings}

    def approve_spec(self) -> None:
        """Gate_Spec human approval (P0: self-approval with audit log)."""
        if self.run.state != "Gate_Spec":
            raise OrchestratorError(
                f"approve_spec from {self.run.state} is illegal")
        self.run._log("Gate_Spec", "approved")
        self.run.state = "Design"

    def run_design_cycle(self) -> dict:
        """Design -> StaticCheck -> (Simulate | retry | escalate)."""
        if self.run.state != "Design":
            raise OrchestratorError(
                f"run_design_cycle from {self.run.state} is illegal")
        self.run.design_rounds += 1
        if self.run.design_rounds > self.run.max_design_rounds:
            self.run.escalated = True
            self.run.finished = True
            self.run._log("Design", "design rounds exhausted -> escalate")
            return {"status": "escalate", "reason": "max design rounds"}

        ctx = ToolContext(run_id=self.run.run_id, role="orchestrator")
        generated = gen_render(self.run.spec_text, ctx)
        if not generated.ok:
            self.run._log("Design", f"generation failed: {generated.errors}")
            self.run.state = "Design"      # fix Spec and resubmit
            return {"status": "retry", "errors": generated.errors}

        static = sta_check(generated.combined, ctx)
        if not static.ok:
            self.run._log("StaticCheck", f"static errors: {static.errors}")
            self.run.state = "Design"
            return {"status": "retry", "errors": static.errors}

        self.run.combined_st = generated.combined
        self.run._log("StaticCheck", "0 errors -> simulate")
        self.run.state = "Simulate"
        return {"status": "simulated"}

    def run_simulation(self) -> dict:
        """Simulate -> Gate_Result | Debug. Only the Orchestrator runs this
        (permission matrix: run_sim lives nowhere else)."""
        if self.run.state != "Simulate":
            raise OrchestratorError(
                f"run_simulation from {self.run.state} is illegal")
        ctx = ToolContext(run_id=self.run.run_id, role="orchestrator",
                          perm="run_sim")
        outcome = sim_run(SimRunIn(
            st_source=self.run.combined_st, suite=self.run.suite,
            plant=self.run.plant_proto,
            pre_scan=self.run.bridge, post_scan=self.run.bridge), ctx)
        if outcome.ok:
            self.run._log("Simulate", "all assertions passed")
            self.run.state = "Gate_Result"
            return {"status": "passed", "digest": outcome.digest}

        self.run.debug_rounds += 1
        self.run._log("Simulate", f"failed: {outcome.errors}")
        if self.run.debug_rounds > self.run.max_debug_rounds:
            self.run.escalated = True
            self.run.finished = True
            self.run._log("Debug", "debug rounds exhausted -> escalate")
            return {"status": "escalate", "reason": "max debug rounds"}
        self.run.state = "Debug"
        return {"status": "failed", "failures": outcome.errors}

    def diagnose(self, case_id: str) -> Diagnosis:
        """Debug: trace.summarize + D1~D8 rules (LLM optional, later)."""
        if self.run.state != "Debug":
            raise OrchestratorError(
                f"diagnose from {self.run.state} is illegal")
        # last Simulate failure is the input to the attribution rules; the
        # full summary wiring (window events from the trace) lands with the
        # G3 gate integration - rules run on what is known here
        failures = ["sim failed (no failure detail available)"]
        summary = trace_summarize(failures, case_id)
        diagnosis = attribute_failure(summary)
        self.run.diagnoses.append(diagnosis)
        self.run._log("Debug", f"{diagnosis.rule}: {diagnosis.conclusion}")
        self.run.state = "Design"          # back to Design with attribution
        return diagnosis

    def approve_result(self) -> None:
        """Gate_Result human approval -> Export."""
        if self.run.state != "Gate_Result":
            raise OrchestratorError(
                f"approve_result from {self.run.state} is illegal")
        self.run._log("Gate_Result", "approved -> export")
        self.run.state = "Export"
        self.run.finished = True
