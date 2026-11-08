"""Trace recording - pure and replayable (15.2).

W1 keeps the in-memory event list and a deterministic SHA256 digest.
Parquet flush (pyarrow) lands with the trace store; the event schema below
matches the 15.2 columns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class TraceEvent:
    scan_no: int
    t_ms: int
    kind: str   # io_write / io_read / state_change / stmt_cov / fault / snapshot
    var: str
    value: str  # stringified for stable hashing


class TraceRecorder:
    """Collects trace events; digest() is the determinism fingerprint."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)

    def digest(self) -> str:
        payload = json.dumps([asdict(e) for e in self.events],
                             sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __len__(self) -> int:
        return len(self.events)
