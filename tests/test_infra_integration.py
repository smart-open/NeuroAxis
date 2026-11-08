"""Live infrastructure probes (task 3). Skips when a host is unreachable.

Auth/config errors still fail loudly - only network-level unreachability
converts into a skip.
"""

import socket

import pytest

from plcagent.config import load_infra_config
from plcagent.storage import objectstore, postgres, redis_client

pytestmark = pytest.mark.integration


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def test_postgres_select_one():
    config = load_infra_config().postgres
    if not _reachable(config.host, config.port):
        pytest.skip(f"postgres unreachable at {config.host}:{config.port}")
    ok, detail = postgres.check(config)
    assert ok, detail


def test_redis_ping():
    config = load_infra_config().redis
    if not _reachable(config.host, config.port):
        pytest.skip(f"redis unreachable at {config.host}:{config.port}")
    ok, detail = redis_client.check(config)
    assert ok, detail


def test_rustfs_list_buckets():
    config = load_infra_config().rustfs
    host = config.endpoint_url.split("//")[-1].split(":")[0]
    port = int(config.endpoint_url.rsplit(":", 1)[1])
    if not _reachable(host, port):
        pytest.skip(f"rustfs unreachable at {config.endpoint_url}")
    ok, detail = objectstore.check(config)
    assert ok, detail
