"""W6 tests: CLI gates command + baseline verify + evidence report."""

from __future__ import annotations

import json

from plcagent.cli import main
from plcagent.verify import run_scenario


def _baseline_digest() -> str:
    digest, _ = run_scenario()
    return digest


def test_cli_gates_passes_d1(capsys):
    exit_code = main(["gates", "--project", "d1"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "G1  PASS" in out and "G5  PASS" in out


def test_cli_gates_json(capsys):
    exit_code = main(["gates", "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    verdict = json.loads(out)
    assert verdict["all_passed"] is True
    assert [g["gate"] for g in verdict["gates"]] == ["G1", "G2", "G3", "G4", "G5"]
    assert len(verdict["verdict_hash"]) == 64


def test_cli_gates_report_writes_md(tmp_path, capsys):
    out_dir = tmp_path / "evidence"
    exit_code = main(["gates", "--report", str(out_dir)])
    assert exit_code == 0
    md = out_dir / "report_d1.md"
    assert md.exists()
    text = md.read_text(encoding="utf-8")
    assert "证据包" in text
    assert "VerdictHash" in text
    # deterministic content: no timestamps
    written = md.read_text(encoding="utf-8")
    assert "G1" in written and "PASS" in written


def test_report_is_deterministic(tmp_path):
    from plcagent.examples.d1_project import (
        D1_SPEC,
        build_suite,
        d1_bridge,
        d1_plant,
    )
    from plcagent.gates import run_gates
    from plcagent.report import render_markdown

    pipeline_a = run_gates(D1_SPEC, build_suite(), d1_plant(),
                           pre_scan=d1_bridge, post_scan=d1_bridge)
    pipeline_b = run_gates(D1_SPEC, build_suite(), d1_plant(),
                           pre_scan=d1_bridge, post_scan=d1_bridge)
    assert render_markdown(pipeline_a, "d1") == render_markdown(pipeline_b, "d1")


def test_cli_verify_baseline_match(tmp_path, capsys):
    baseline_dir = tmp_path / "expected"
    baseline_dir.mkdir()
    (baseline_dir / "baseline.txt").write_text(_baseline_digest(),
                                               encoding="utf-8")
    exit_code = main(["verify", "--runs", "2",
                      "--baseline", str(baseline_dir)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "matches baseline" in out


def test_cli_verify_baseline_mismatch(tmp_path, capsys):
    baseline_dir = tmp_path / "expected"
    baseline_dir.mkdir()
    (baseline_dir / "baseline.txt").write_text("deadbeef" * 8,
                                               encoding="utf-8")
    exit_code = main(["verify", "--runs", "1",
                      "--baseline", str(baseline_dir)])
    assert exit_code == 2
    assert "mismatch" in capsys.readouterr().out


def test_cli_verify_baseline_missing_file(tmp_path, capsys):
    exit_code = main(["verify", "--runs", "1",
                      "--baseline", str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 3                  # environment error (18.2)
    assert "missing" in out
