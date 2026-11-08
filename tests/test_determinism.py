"""Acceptance A2: same inputs -> identical trace digest.

Unit scope runs 50 iterations; CI scales the same check to 1000 (14.2).
"""

from plcagent.verify import check_determinism, run_once


def test_50_runs_identical_digest():
    ok, detail = check_determinism(50)
    assert ok, detail


def test_digest_is_stable_sha256_hex():
    digest = run_once()
    assert len(digest) == 64
    assert digest == run_once()
