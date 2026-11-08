"""W4 tests: D1 sample project (spec -> generated ST -> plant -> DSL)."""

from __future__ import annotations

from plcagent.dsl import run_suite
from plcagent.examples.d1_project import (
    D1_SPEC,
    apply_bridge,
    build_suite,
    d1_generated_st,
    d1_plant,
)
from plcagent.gen import render
from plcagent.spec.loader import load_spec
from plcagent.sta import check_ir, check_st


def _run_d1():
    """Full D1 chain with the plant bridge applied between scans."""
    import plcagent.dsl as dsl

    st = d1_generated_st()
    suite = build_suite()
    plant_proto = d1_plant()

    # wrap _one_scan to apply the bidirectional bridge around the scan:
    # PLC outputs -> plant before physics, plant inputs -> PLC after.
    original_one_scan = dsl._one_scan

    def bridged_one_scan(interp, plant, scan_ms, never_rules, view,
                         outcome, scan):
        # program outputs (interpreter env, direction=="output") -> plant
        for decl in interp.pou.decls:
            if decl.direction == "output":
                plant.outputs[decl.name] = interp.env.values[decl.name]
        apply_bridge(plant)                  # PLC -> plant direction
        original_one_scan(interp, plant, scan_ms, never_rules, view,
                          outcome, scan)
        apply_bridge(plant)                  # plant -> PLC direction

    dsl._one_scan = bridged_one_scan
    try:
        return run_suite(st, suite, plant_proto, scan_ms=10, max_scans=3000)
    finally:
        dsl._one_scan = original_one_scan


def test_d1_spec_passes_r_rules():
    ir = load_spec(D1_SPEC)
    assert check_ir(ir) == []


def test_d1_generated_st_passes_s_rules():
    result = render(load_spec(D1_SPEC))
    problems = check_st(result.combined)
    assert problems == [], [p.message for p in problems]


def test_d1_suite_all_green():
    result = _run_d1()
    assert result.passed, [(c.case_id, c.failures) for c in result.cases]
    assert {c.case_id for c in result.cases} == {"estop_immediate", "push_cycle"}


def test_d1_deterministic():
    digests = {_run_d1().digest for _ in range(3)}
    assert len(digests) == 1
