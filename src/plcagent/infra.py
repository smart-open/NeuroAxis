"""Infrastructure connectivity checks used by CLI and test suite."""

from __future__ import annotations

from plcagent.config import InfraConfig, load_infra_config
from plcagent.storage import objectstore, postgres, redis_client


def check_all(config: InfraConfig | None = None) -> dict[str, tuple[bool, str]]:
    """Probe all three base services; returns {service: (ok, detail)}."""
    config = config or load_infra_config()
    return {
        "postgres": postgres.check(config.postgres),
        "redis": redis_client.check(config.redis),
        "rustfs": objectstore.check(config.rustfs),
    }
