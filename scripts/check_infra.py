"""Thin wrapper: python scripts/check_infra.py == plcagent infra."""

from plcagent.cli import main

if __name__ == "__main__":
    raise SystemExit(["infra"])
