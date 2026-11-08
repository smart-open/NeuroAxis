"""Command line entry. Grows with the plan (18.2 full command set)."""

from __future__ import annotations

import argparse

from plcagent import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="plcagent", description="NeuroAxis PLC agent")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify", help="determinism check (acceptance A2)")
    verify.add_argument("--runs", type=int, default=50, metavar="N",
                        help="number of simulation runs to compare (default 50)")
    verify.add_argument("--baseline", metavar="DIR",
                        help="compare the trace digest against DIR/baseline.txt")

    gates = sub.add_parser("gates", help="run G1~G5 on a sample project")
    gates.add_argument("--project", default="d1", choices=["d1"],
                       help="built-in project id (default d1)")
    gates.add_argument("--report", metavar="DIR",
                       help="write the evidence report (md/pdf) into DIR")
    gates.add_argument("--json", action="store_true",
                       help="print the machine-readable verdict JSON")

    sub.add_parser("infra", help="check PostgreSQL / Redis / RustFS connectivity")

    args = parser.parse_args(argv)

    if args.command == "verify":
        from plcagent.verify import check_determinism
        print(f"running determinism check with {args.runs} runs ...")
        ok, digest_or_error = check_determinism(args.runs)
        if ok and args.baseline:
            from pathlib import Path

            baseline_file = Path(args.baseline) / "baseline.txt"
            if not baseline_file.exists():
                print(f"FAIL: baseline file missing: {baseline_file}")
                return 3                       # environment error (18.2)
            expected = baseline_file.read_text(encoding="utf-8").strip()
            if expected != digest_or_error:
                print(f"FAIL: baseline mismatch: expected {expected[:16]}..., "
                      f"got {digest_or_error[:16]}...")
                return 2
            print(f"PASS: matches baseline {expected[:16]}...")
            return 0
        if ok:
            print(f"PASS: trace SHA256 = {digest_or_error[:16]}...")
            return 0
        print(f"FAIL: {digest_or_error}")
        return 2

    if args.command == "gates":
        from plcagent.examples.d1_project import (
            D1_SPEC,
            build_suite,
            d1_bridge,
            d1_plant,
        )
        from plcagent.gates import run_gates

        if args.project == "d1":
            pipeline = run_gates(D1_SPEC, build_suite(), d1_plant(),
                                 pre_scan=d1_bridge, post_scan=d1_bridge)
        if args.json:
            from plcagent.report import verdict_json

            print(verdict_json(pipeline))
        else:
            for result in pipeline.results:
                mark = "PASS" if result.passed else "FAIL"
                print(f"{result.gate}  {mark}  {'; '.join(result.details)}")
        if args.report:
            from plcagent.report import write_report

            written = write_report(pipeline, args.project, args.report)
            for kind, path in written.items():
                print(f"report {kind}: {path}")
        return 0 if pipeline.all_passed else 2

    if args.command == "infra":
        from plcagent.infra import check_all
        results = check_all()
        failed = False
        for service, (ok, detail) in results.items():
            mark = "PASS" if ok else "FAIL"
            print(f"{mark}  {service:9s} {detail}")
            failed = failed or not ok
        return 1 if failed else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
