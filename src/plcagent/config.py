"""Infrastructure configuration.

Precedence: environment variables (PLCAGENT_*) > config/infra.toml > defaults.
config/infra.toml holds the real credentials and is gitignored; the tracked
template is config/infra.example.toml.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PostgresConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def conninfo(self) -> str:
        return (f"host={self.host} port={self.port} user={self.user} "
                f"password={self.password} dbname={self.database}")


@dataclass(frozen=True, slots=True)
class RedisConfig:
    host: str
    port: int
    password: str


@dataclass(frozen=True, slots=True)
class RustFsConfig:
    endpoint_url: str
    access_key: str
    secret_key: str


@dataclass(frozen=True, slots=True)
class InfraConfig:
    postgres: PostgresConfig
    redis: RedisConfig
    rustfs: RustFsConfig


_DEFAULTS = {
    "pg_host": "localhost",
    "pg_port": 5432,
    "pg_user": "postgres",
    "pg_password": "",
    "pg_database": "neuroaxis",
    "redis_host": "localhost",
    "redis_port": 6379,
    "redis_password": "",
    "rustfs_endpoint": "http://localhost:7000",
    "rustfs_access_key": "",
    "rustfs_secret_key": "",
}


def load_infra_config(config_path: str | None = None) -> InfraConfig:
    """Build the infra config: defaults <- infra.toml <- environment."""
    values = dict(_DEFAULTS)

    candidate = _find_config_file(config_path)
    if candidate is not None and candidate.is_file():
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        pg = data.get("postgres", {})
        rd = data.get("redis", {})
        fs = data.get("rustfs", {})
        values.update({
            "pg_host": pg.get("host", values["pg_host"]),
            "pg_port": int(pg.get("port", values["pg_port"])),
            "pg_user": pg.get("user", values["pg_user"]),
            "pg_password": pg.get("password", values["pg_password"]),
            "pg_database": pg.get("database", values["pg_database"]),
            "redis_host": rd.get("host", values["redis_host"]),
            "redis_port": int(rd.get("port", values["redis_port"])),
            "redis_password": rd.get("password", values["redis_password"]),
            "rustfs_endpoint": fs.get("endpoint", values["rustfs_endpoint"]),
            "rustfs_access_key": fs.get("access_key", values["rustfs_access_key"]),
            "rustfs_secret_key": fs.get("secret_key", values["rustfs_secret_key"]),
        })

    # Environment overrides (PLCAGENT_PG_HOST etc.), empty string = not set.
    env_map = {
        "pg_host": "PLCAGENT_PG_HOST",
        "pg_port": "PLCAGENT_PG_PORT",
        "pg_user": "PLCAGENT_PG_USER",
        "pg_password": "PLCAGENT_PG_PASSWORD",
        "pg_database": "PLCAGENT_PG_DATABASE",
        "redis_host": "PLCAGENT_REDIS_HOST",
        "redis_port": "PLCAGENT_REDIS_PORT",
        "redis_password": "PLCAGENT_REDIS_PASSWORD",
        "rustfs_endpoint": "PLCAGENT_RUSTFS_ENDPOINT",
        "rustfs_access_key": "PLCAGENT_RUSTFS_ACCESS_KEY",
        "rustfs_secret_key": "PLCAGENT_RUSTFS_SECRET_KEY",
    }
    for key, env_name in env_map.items():
        env_value = os.environ.get(env_name, "")
        if env_value:
            values[key] = int(env_value) if key.endswith("port") else env_value

    return InfraConfig(
        postgres=PostgresConfig(
            host=values["pg_host"], port=values["pg_port"], user=values["pg_user"],
            password=values["pg_password"], database=values["pg_database"]),
        redis=RedisConfig(
            host=values["redis_host"], port=values["redis_port"],
            password=values["redis_password"]),
        rustfs=RustFsConfig(
            endpoint_url=values["rustfs_endpoint"],
            access_key=values["rustfs_access_key"],
            secret_key=values["rustfs_secret_key"]),
    )

def _find_config_file(config_path: str | None) -> Path | None:
    """Explicit path wins; otherwise search config/infra.toml upward from CWD
    so the API server works from any working directory."""
    if config_path:
        return Path(config_path)
    cwd = Path.cwd()
    for base in (cwd, *cwd.parents):
        candidate = base / "config" / "infra.toml"
        if candidate.is_file():
            return candidate
    return None
