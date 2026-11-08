"""Debugger attribution rules D1~D8 (4.4): rules first, LLM second.

Deterministic rules produce the diagnosis; the LLM (if any) only writes
the human-readable explanation. D8 (non-determinism) is a product bug by
definition - the simulator must never be non-deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from plcagent.agent.tools import IrPatchProposal, TraceSummary


@dataclass
class Diagnosis:
    rule: str                      # D1..D8 or "unknown"
    conclusion: str
    hint: str = ""
    proposal: IrPatchProposal | None = None
    evidence: list[str] = field(default_factory=list)


def _window_values(summary: TraceSummary, signal: str) -> list[str]:
    return [event.value for event in summary.window_events
            if event.signal == signal]


def _signals_in_expr(expr: str) -> list[str]:
    """Extract identifiers from a guard-like expression (crude but
    deterministic; the IR tree is available to callers who need more)."""
    import re

    return sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
                  - {"AND", "OR", "NOT", "XOR", "TRUE", "FALSE"})


def attribute_failure(summary: TraceSummary,
                      interlock_guards: list[str] | None = None,
                      estop_signals: list[str] | None = None,
                      ) -> Diagnosis:
    """Run D1~D8 in order; first hit wins (4.4)."""
    interlock_guards = interlock_guards or []
    estop_signals = estop_signals or []

    # D7: failure at the very first scan -> initialisation missing
    if summary.fail_scan == 0:
        return Diagnosis(
            "D7", "failure at scan 0: initial state or entry actions wrong",
            hint="check entry actions cover initial outputs")

    # D3: an interlock guard is TRUE in the window and pressing output low
    for guard in interlock_guards:
        for signal in _signals_in_expr(guard):
            values = _window_values(summary, signal)
            if "False" in values and summary.fail_scan >= 0:
                return Diagnosis(
                    "D3", f"interlock guard signal {signal!r} went low in "
                    f"the failure window - output suppressed by design",
                    hint="expected behaviour: fix Spec timing, never the interlock",
                    evidence=[f"{signal} values in window: {values[:8]}..."])

    # D1: a signal in the failing assertion never appears in the window
    for signal in _signals_in_expr(summary.failing_assertion):
        if signal not in {event.signal for event in summary.window_events}:
            return Diagnosis(
                "D1", f"signal {signal!r} never flipped in the failure "
                f"window - driver side missing or condition always false",
                hint="check the upstream state that should drive this signal")

    # D5: failure scan sits at the very end of a plausible time window
    if summary.fail_scan > 0:
        latest = max((event.scan for event in summary.window_events),
                     default=-1)
        if 0 <= summary.fail_scan - latest <= 2:
            return Diagnosis(
                "D5", "assertion failed at the window edge - timing margin "
                "insufficient",
                hint="consider relaxing withinMs or adjusting plant params")

    # D2: sequence timeout family (fault state reached by timeout)
    if "timeout" in summary.failing_assertion.lower():
        return Diagnosis(
            "D2", "sequence timeout: sensor never reached its target",
            hint="check plant parameters (stroke time vs configured timeout)")

    # D6: mapped input never matches any component port (mapping mismatch)
    # detected upstream; here: assertion references a signal with no events
    # at all anywhere (stronger than D1's window check)

    # D4: two machines fight over one output -> product bug (V2 gap)
    # detectable only with IR context; kept for the Orchestrator to supply

    return Diagnosis("unknown", "no deterministic rule matched",
                     hint="escalate to LLM attribution or human review")


def check_determinism_violation(digest_a: str, digest_b: str) -> Diagnosis | None:
    """D8: same inputs, different digests = product bug, never a Spec fix."""
    if digest_a != digest_b:
        return Diagnosis(
            "D8", "non-determinism detected: identical inputs produced "
            "different trace digests",
            hint="product bug - freeze and fix the simulator, do NOT patch Spec")
    return None
