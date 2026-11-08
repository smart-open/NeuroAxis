"""W4 tests: D1 sample project (spec -> generated ST -> plant -> DSL)."""

from __future__ import annotations

from plcagent.dsl import run_suite
from plcagent.examples.d1_project import (
    D1_SPEC,
    build_suite,
    d1_bridge,
    d1_generated_st,
    d1_plant,
)
from plcagent.gen import render
from plcagent.spec.loader import load_spec
from plcagent.sta import check_ir, check_st


def _run_d1():
    st = d1_generated_st()
    suite = build_suite()
    plant_proto = d1_plant()

    # the d1 bridge hook runs both directions around each scan
    return run_suite(st, suite, plant_proto, scan_ms=10, max_scans=3000,
                     pre_scan=d1_bridge, post_scan=d1_bridge)


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
    assert {c.case_id for c in result.cases} == {
        "estop_immediate", "push_cycle", "recover_and_return"}


def test_d1_deterministic():
    digests = {_run_d1().digest for _ in range(3)}
    assert len(digests) == 1
