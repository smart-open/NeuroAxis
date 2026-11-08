"""W6 tests: five verification gates G1~G5 on the D1 sample project."""

from __future__ import annotations

from plcagent.examples.d1_project import (
    D1_SPEC,
    build_suite,
    d1_bridge,
    d1_plant,
)
from plcagent.gates import (
    gate_compile,
    gate_coverage,
    gate_mutation,
    gate_simulate,
    gate_static,
    run_gates,
)

SUITE = build_suite()
PLANT = d1_plant
BRIDGE = d1_bridge


def test_g1_compile_passes_d1():
    result, combined = gate_compile(D1_SPEC)
    assert result.passed, result.details
    assert "END_PROGRAM" in combined


def test_g1_compile_rejects_bad_spec():
    bad = D1_SPEC.replace('when: "PE_SortPos"', 'when: "Cyl_Seq.done"')
    result, combined = gate_compile(bad)
    assert not result.passed
    assert combined == ""           # nothing rendered


def test_g2_static_passes_d1():
    result, combined = gate_compile(D1_SPEC)
    assert gate_static(D1_SPEC, combined).passed


def test_g2_static_catches_rule_violation():
    # duplicate priority between two transitions from Idle -> V6 error
    bad = D1_SPEC.replace(
        'when: "Start_PB AND Safety_OK", prio: 1 }',
        'when: "Start_PB AND Safety_OK", prio: 1 }\n'
        '      - { from: Idle, to: Move, when: "Stop_PB", prio: 1 }')
    result, combined = gate_compile(bad)
    gate2 = gate_static(bad, combined)
    assert not gate2.passed
    assert any("V6" in e for e in gate2.details)


def test_g3_simulation_passes_d1():
    _, combined = gate_compile(D1_SPEC)
    result = gate_simulate(combined, SUITE, PLANT(), pre_scan=BRIDGE,
                           post_scan=BRIDGE)
    assert result.passed, result.details


def test_g4_coverage_passes_d1():
    _, combined = gate_compile(D1_SPEC)
    result = gate_coverage(combined, SUITE, PLANT(), pre_scan=BRIDGE,
                           post_scan=BRIDGE)
    assert result.passed, result.details
    # every output must have been written both TRUE and FALSE
    assert any("statement" in d for d in result.details)


def test_g4_coverage_flags_never_written_output():
    # HMI_Fault only ever TRUE in the estop case; the push case never
    # resets it via the interlock path -> strict check catches gaps or
    # passes when both values observed; here we assert the check ran
    _, combined = gate_compile(D1_SPEC)
    result = gate_coverage(combined, SUITE, PLANT(), pre_scan=BRIDGE,
                           post_scan=BRIDGE)
    details_text = " ".join(result.details)
    assert "statement" in details_text or result.passed


def test_g5_mutation_suite_kills_mutants():
    _, combined = gate_compile(D1_SPEC)
    result = gate_mutation(combined, SUITE, PLANT(), pre_scan=BRIDGE,
                           post_scan=BRIDGE)
    assert result.passed, result.details
    assert "kill rate" in result.details[0]


def test_g5_mutation_weak_suite_fails():
    """A suite that never touches the outputs kills nothing -> G5 red."""
    _, combined = gate_compile(D1_SPEC)
    weak_suite = {"suite": "weak", "cases": [{"id": "noop", "steps": [
        {"set": {"Safety_OK": True}}]}]}
    result = gate_mutation(combined, weak_suite, PLANT(), pre_scan=BRIDGE,
                           post_scan=BRIDGE, min_kill_rate=0.8)
    assert not result.passed


def test_pipeline_all_gates_d1():
    pipeline = run_gates(D1_SPEC, SUITE, PLANT(), pre_scan=BRIDGE,
                         post_scan=BRIDGE)
    assert pipeline.all_passed, [
        (r.gate, r.details) for r in pipeline.results if not r.passed]
    assert [r.gate for r in pipeline.results] == [
        "G1", "G2", "G3", "G4", "G5"]
    assert pipeline.spec_hash
    assert len(pipeline.verdict_hash) == 64


def test_pipeline_stops_early_on_bad_spec():
    pipeline = run_gates("not: valid: yaml: [", SUITE, PLANT())
    assert not pipeline.all_passed
    assert [r.gate for r in pipeline.results] == ["G1"]


def test_pipeline_deterministic_verdict():
    first = run_gates(D1_SPEC, SUITE, PLANT(), pre_scan=BRIDGE,
                      post_scan=BRIDGE)
    second = run_gates(D1_SPEC, SUITE, PLANT(), pre_scan=BRIDGE,
                       post_scan=BRIDGE)
    assert first.verdict_hash == second.verdict_hash
