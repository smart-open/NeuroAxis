"""Virtual clock - decoupled from wall time (determinism contract).

simTime = scanNo * scanMs. The whole simulation is a pure function of the
input sequence: same inputs produce byte-identical traces (acceptance A2).
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_SCAN_MS = (1, 5, 10, 20, 50)  # V11


@dataclass(slots=True)
class VirtualClock:
    """Monotonic scan counter; t_ms is the virtual time at scan start."""

    scan_ms: int
    scan_no: int = 0

    def __post_init__(self) -> None:
        if self.scan_ms not in ALLOWED_SCAN_MS:
            raise ValueError(f"scanMs must be one of {ALLOWED_SCAN_MS} (V11), got {self.scan_ms}")

    @property
    def t_ms(self) -> int:
        return self.scan_no * self.scan_ms

    def advance(self) -> None:
        self.scan_no += 1
