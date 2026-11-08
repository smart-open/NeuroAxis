"""D1-style sorting conveyor: the W1 canonical self-test scenario.

Timeline per 40-scan cycle (scanMs=10):
  scan 0        Start pulse -> state 1
  scans 1..19   conveyor runs
  scans 20..24  photoelectric sensor PE covered -> state 2 -> push -> state 0
  scan 100      EStop asserted once -> everything off (interlock behaviour)
"""

from __future__ import annotations

SAMPLE_ST = """
PROGRAM Sorter
VAR_INPUT
    Start : BOOL;
    PE : BOOL;
    EStop : BOOL;
END_VAR
VAR_OUTPUT
    Conv : BOOL;
    Push : BOOL;
END_VAR
VAR
    State : DINT;
END_VAR

IF EStop THEN
    State := 3;
    Conv := FALSE;
    Push := FALSE;
ELSIF State = 0 AND Start THEN
    State := 1;
ELSIF State = 1 THEN
    Conv := TRUE;
    IF PE THEN
        State := 2;
    END_IF;
ELSIF State = 2 THEN
    Conv := FALSE;
    Push := TRUE;
    State := 0;
END_IF;
END_PROGRAM
"""

SCAN_MS = 10
TOTAL_SCANS = 200


def input_at(scan: int) -> dict[str, bool]:
    phase = scan % 40
    return {
        "Start": phase == 0,
        "PE": 20 <= phase < 25,
        "EStop": scan == 100,
    }


def scenario_inputs() -> list[dict[str, bool]]:
    return [input_at(scan) for scan in range(TOTAL_SCANS)]
