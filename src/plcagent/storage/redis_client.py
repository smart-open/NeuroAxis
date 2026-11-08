"""Redis access (cache & queue, 8.3)."""

from __future__ import annotations

from plcagent.config import RedisConfig


def client(config: RedisConfig):
    """Create a redis-py client; raises with install hint if driver missing."""
    try:
        import redis
    except ImportError as exc:
        raise RuntimeError(
            "redis-py not installed; run: pip install 'plcagent[infra]'") from exc
    return redis.Redis(host=config.host, port=config.port,
                       password=config.password or None,
                       socket_connect_timeout=5)


def check(config: RedisConfig) -> tuple[bool, str]:
    """PING probe. Returns (ok, detail)."""
    try:
        with client(config) as conn:
            if conn.ping():
                return True, f"{config.host}:{config.port} ok"
            return False, "ping returned false"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
