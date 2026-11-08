"""W5 tests: agent tools + Debugger attribution + LLM gateway + Orchestrator."""

from __future__ import annotations

import json

import pytest

from plcagent.agent.debugger import attribute_failure, check_determinism_violation
from plcagent.agent.llm import LLMError, LlmGateway
from plcagent.agent.orchestrator import Orchestrator, OrchestratorError, RunState
from plcagent.agent.tools import (
    SimRunIn,
    ToolContext,
    gen_render,
    ir_check,
    sim_run,
    sta_check,
    trace_summarize,
)
from plcagent.examples.d1_project import (
    D1_SPEC,
    build_suite,
    d1_bridge,
    d1_generated_st,
    d1_plant,
)

CTX = ToolContext(run_id="r1", role="orchestrator")


GOOD_SPEC = D1_SPEC

BAD_SPEC = GOOD_SPEC.replace(
    "- { from: Idle,   to: Move,  when: \"Start_PB AND Safety_OK\", prio: 1 }",
    "- { from: Idle,   to: Move,  when: \"Start_PB AND Safety_OK\", prio: 1 }\n"
    "      - { from: Idle,   to: Move,  when: \"Stop_PB\", prio: 1 }")


# ---------------- tools ----------------

def test_spec_validate_passes_good_spec():
    from plcagent.agent.tools import spec_validate

    result = spec_validate(GOOD_SPEC, CTX)
    assert result.ok and result.spec_hash


def test_ir_check_catches_duplicate_priority():
    result = ir_check(BAD_SPEC, CTX)
    assert not result.ok
    assert any("V6" in e for e in result.errors)


def test_gen_render_is_pure():
    first = gen_render(GOOD_SPEC, CTX)
    second = gen_render(GOOD_SPEC, CTX)
    assert first.ok and second.ok
    assert first.combined == second.combined
    assert first.spec_hash == second.spec_hash


def test_sta_check_clean_generated_st():
    generated = gen_render(GOOD_SPEC, CTX)
    result = sta_check(generated.combined, CTX)
    assert result.ok, result.errors


def test_sim_run_permission_gate():
    locked = ToolContext(run_id="r1", role="designer", perm="read")
    outcome = sim_run(SimRunIn(
        st_source=d1_generated_st(), suite=build_suite(),
        plant=d1_plant()), locked)
    assert not outcome.ok
    assert "run_sim" in outcome.errors[0]


def test_sim_run_orchestrator_passes():
    ctx = ToolContext(run_id="r1", role="orchestrator", perm="run_sim")
    outcome = sim_run(SimRunIn(
        st_source=d1_generated_st(), suite=build_suite(),
        plant=d1_plant(), pre_scan=d1_bridge, post_scan=d1_bridge), ctx)
    assert outcome.ok, outcome.errors
    assert outcome.digest


def test_trace_summarize_extracts_fail_scan():
    summary = trace_summarize(
        ["[push] expect {'X': True} not met at scan 42)"], "push")
    assert summary.fail_scan == 42
    assert "push" in summary.failing_assertion


def test_trace_summarize_window_events():
    timelines = {"A": {10: "True", 30: "False", 45: "True"},
                 "B": {20: "True"}}
    summary = trace_summarize(["fail at scan 40)"], "c", timelines,
                              window_scans=25)
    scans = {event.scan for event in summary.window_events}
    assert scans == {20, 30}          # only within [15, 40]


# ---------------- Debugger attribution ----------------

def _summary(fail_scan: int, assertion: str, events: list[tuple[int, str, str]]):
    from plcagent.agent.tools import SignalEvent, TraceSummary

    return TraceSummary(
        failing_assertion=assertion, fail_scan=fail_scan,
        window_events=[SignalEvent(scan=s, signal=sig, value=v)
                       for s, sig, v in events])


def test_d7_first_scan_failure():
    diagnosis = attribute_failure(_summary(0, "expect X", []))
    assert diagnosis.rule == "D7"


def test_d1_signal_never_flipped():
    summary = _summary(50, "Ghost_Signal AND Motor_Run",
                       [(20, "Motor_Run", "True")])
    diagnosis = attribute_failure(summary)
    assert diagnosis.rule == "D1"
    assert "Ghost_Signal" in diagnosis.conclusion


def test_d3_interlock_suppression():
    summary = _summary(60, "Conv_Run", [(55, "Safety_OK", "False")])
    diagnosis = attribute_failure(summary, interlock_guards=["NOT Safety_OK"])
    assert diagnosis.rule == "D3"
    assert "interlock" in diagnosis.conclusion


def test_d5_window_edge_failure():
    summary = _summary(100, "X", [(99, "X", "False")])
    diagnosis = attribute_failure(summary)
    assert diagnosis.rule == "D5"


def test_d8_determinism_violation():
    diagnosis = check_determinism_violation("aaa", "bbb")
    assert diagnosis is not None and diagnosis.rule == "D8"
    assert check_determinism_violation("same", "same") is None


def test_unknown_falls_through():
    summary = _summary(30, "X", [(10, "X", "False"), (20, "X", "True")])
    diagnosis = attribute_failure(summary)
    assert diagnosis.rule in ("D5", "unknown")


# ---------------- LLM gateway ----------------

class FakeClient:
    """Scripted responses for deterministic tests."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, system, user, json_schema=None):
        return self.responses.pop(0)


SCHEMA = {"type": "object", "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}


def test_llm_success_and_accounting():
    gateway = LlmGateway(client=FakeClient(['{"answer": "ok"}']))
    payload = gateway.chat("sys", "user", "test", SCHEMA)
    assert payload == {"answer": "ok"}
    assert gateway.calls_used == 1
    assert gateway.budget_used == pytest.approx(0.01)


def test_llm_retries_invalid_json_then_succeeds():
    gateway = LlmGateway(client=FakeClient(["not json", '{"answer": "ok"}']))
    payload = gateway.chat("sys", "user", "test", SCHEMA)
    assert payload == {"answer": "ok"}
    assert gateway.calls_used == 1


def test_llm_fails_after_retries():
    gateway = LlmGateway(client=FakeClient(["bad", "bad", "bad"]))
    with pytest.raises(LLMError, match="fall back to rule engine"):
        gateway.chat("sys", "user", "test", SCHEMA)


def test_llm_budget_call_cap():
    gateway = LlmGateway(client=FakeClient([json.dumps({"answer": "x"})] * 5),
                         max_calls_per_run=2)
    gateway.chat("sys", "user", "t")
    gateway.chat("sys", "user", "t")
    with pytest.raises(LLMError, match="E-LLM-BUDGET"):
        gateway.chat("sys", "user", "t")


def test_llm_budget_money_cap():
    gateway = LlmGateway(client=FakeClient([json.dumps({"answer": "x"})] * 3),
                         cost_per_call_cny=3.0, budget_cny_per_run=6.0)
    gateway.chat("sys", "user", "t")
    gateway.chat("sys", "user", "t")      # budget_used = 6.0 >= 6.0
    with pytest.raises(LLMError, match="E-LLM-BUDGET"):
        gateway.chat("sys", "user", "t")


def test_llm_schema_rejection_retries():
    # response is valid JSON but violates the schema -> retry -> fail
    gateway = LlmGateway(client=FakeClient(['{"wrong": 1}'] * 3))
    with pytest.raises(LLMError):
        gateway.chat("sys", "user", "test", SCHEMA)


# ---------------- Orchestrator ----------------

def _fresh_run():
    return RunState(run_id="run-1", spec_text=GOOD_SPEC,
                    suite=build_suite(), plant_proto=d1_plant(),
                    bridge=d1_bridge)


def test_orchestrator_happy_path():
    orch = Orchestrator(_fresh_run())
    orch.start()
    result = orch.submit_spec(GOOD_SPEC)
    assert result["ok"]
    orch.approve_spec()
    assert orch.run_design_cycle()["status"] == "simulated"
    assert orch.run_simulation()["status"] == "passed"
    orch.approve_result()
    assert orch.run.finished and orch.run.state == "Export"


def test_orchestrator_permission_matrix_enforced():
    orch = Orchestrator(_fresh_run())
    orch.start()
    # designer calling sim directly is blocked at the tool layer
    from plcagent.agent.tools import sim_run as sim_tool

    outcome = sim_tool(SimRunIn(st_source="", suite={}, plant=d1_plant()),
                       ToolContext(run_id="x", role="designer"))
    assert not outcome.ok


def test_orchestrator_illegal_transition():
    orch = Orchestrator(_fresh_run())
    with pytest.raises(OrchestratorError):
        orch.approve_spec()               # still in Intake


def test_orchestrator_design_round_budget():
    run = _fresh_run()
    run.max_design_rounds = 1
    orch = Orchestrator(run)
    orch.start()
    orch.submit_spec(GOOD_SPEC)
    orch.approve_spec()
    # force generation failure with a Spec that cannot generate (sequence
    # member guard) - round 1 retries, round 2 exceeds budget
    broken = GOOD_SPEC.replace(
        'when: "PE_SortPos"', 'when: "Cyl_Seq.done"')
    broken = broken.replace("interlocks:", "sequences:\n"
                            "  - name: Cyl_Seq\n    type: ExtendRetract\n"
                            "    bind: { out: Conv_Run }\ninterlocks:")
    run.spec_text = broken
    first = orch.run_design_cycle()
    assert first["status"] == "retry"
    second = orch.run_design_cycle()
    assert second["status"] == "escalate"
    assert run.escalated and run.finished
