"""Virtual clock (5.1 / V11)."""

import pytest

from plcagent.trace.clock import VirtualClock


def test_time_is_scan_no_times_scan_ms():
    clock = VirtualClock(scan_ms=10)
    assert clock.t_ms == 0
    clock.advance()
    clock.advance()
    assert clock.t_ms == 20


def test_scan_ms_whitelist():
    for ok in (1, 5, 10, 20, 50):
        VirtualClock(scan_ms=ok)
    with pytest.raises(ValueError):
        VirtualClock(scan_ms=7)
