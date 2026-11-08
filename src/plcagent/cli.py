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

    sub.add_parser("infra", help="check PostgreSQL / Redis / RustFS connectivity")

    args = parser.parse_args(argv)

    if args.command == "verify":
        from plcagent.verify import check_determinism
        print(f"running determinism check with {args.runs} runs ...")
        ok, digest_or_error = check_determinism(args.runs)
        if ok:
            print(f"PASS: trace SHA256 = {digest_or_error[:16]}...")
            return 0
        print(f"FAIL: {digest_or_error}")
        return 2

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
