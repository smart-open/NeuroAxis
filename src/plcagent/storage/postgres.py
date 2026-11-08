"""PostgreSQL access (lazy import so the core stays dependency-free)."""

from __future__ import annotations

from plcagent.config import PostgresConfig


def connect(config: PostgresConfig):
    """Open a psycopg connection; raises with install hint if driver missing."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg not installed; run: pip install 'plcagent[infra]'") from exc
    # kwargs instead of a conninfo string: passwords may contain spaces or
    # special characters that would break string parsing.
    return psycopg.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        dbname=config.database,
        connect_timeout=5,
    )


def check(config: PostgresConfig) -> tuple[bool, str]:
    """SELECT 1 probe. Returns (ok, detail)."""
    try:
        with connect(config) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                row = cur.fetchone()
        if row == (1,):
            return True, f"{config.host}:{config.port}/{config.database} ok"
        return False, f"unexpected result {row!r}"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - probe reports any failure
        return False, f"{type(exc).__name__}: {exc}"
