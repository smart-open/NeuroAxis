"""Switch infra environment.

Usage:
  python scripts/switch_env.py a    # 192.168.106.128 (PG:5435 Redis RustFS:9000)
  python scripts/switch_env.py b    # 192.168.106.128 (PG:5432 Redis RustFS:7000)
  python scripts/switch_env.py      # show current config + reachability

Writes config/infra.toml (gitignored) with the selected credentials.
"""

from __future__ import annotations

import io
import socket
import sys
import tomllib
from pathlib import Path

CONFIG_PATH = Path("config/infra.toml")

ENVIRONMENTS = {
    "a": {
        "label": "server 192.168.106.128 (PG 5435 / RustFS 9000)",
        "postgres": {"host": "192.168.106.128", "port": 5435, "user": "postgres",
                     "password": "Postgres123!", "database": "neuroaxis"},
        "redis": {"host": "192.168.106.128", "port": 6379, "password": "Redis123!"},
        "rustfs": {"endpoint": "http://192.168.106.128:9000",
                   "access_key": "c35bbfa957cdcd122608",
                   "secret_key": "d4b9cf9171957b567edd0424dc19f35902afc473"},
    },
    "b": {
        "label": "local VM 192.168.106.128 (PG 5432 / RustFS 7000)",
        "postgres": {"host": "192.168.106.128", "port": 5432, "user": "postgres",
                     "password": "abc123", "database": "neuroaxis"},
        "redis": {"host": "192.168.106.128", "port": 6379, "password": "abc123"},
        "rustfs": {"endpoint": "http://192.168.106.128:7000",
                   "access_key": "HqmHMOLvAsveNQ5TjXxQ",
                   "secret_key": "aeyuglGqUt4QOKOAIxDlu2rK1UB5nK95PWI8p2cF"},
    },
}


def render_toml(env: dict) -> str:
    pg, rd, fs = env["postgres"], env["redis"], env["rustfs"]
    return (
        "# REAL infrastructure credentials - gitignored, never commit.\n"
        f"# environment: {env['label']}\n\n"
        "[postgres]\n"
        f'host = "{pg["host"]}"\n'
        f'port = {pg["port"]}\n'
        f'user = "{pg["user"]}"\n'
        f'password = "{pg["password"]}"\n'
        f'database = "{pg["database"]}"\n\n'
        "[redis]\n"
        f'host = "{rd["host"]}"\n'
        f'port = {rd["port"]}\n'
        f'password = "{rd["password"]}"\n\n'
        "[rustfs]\n"
        f'endpoint = "{fs["endpoint"]}"\n'
        f'access_key = "{fs["access_key"]}"\n'
        f'secret_key = "{fs["secret_key"]}"\n'
    )


def tcp_ok(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def show_current() -> None:
    if not CONFIG_PATH.is_file():
        print("config/infra.toml does not exist yet")
        return
    data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    pg, rd, fs = data["postgres"], data["redis"], data["rustfs"]
    fs_host = fs["endpoint"].split("//")[-1].split(":")[0]
    fs_port = int(fs["endpoint"].rsplit(":", 1)[1])
    print(f"current: pg={pg['host']}:{pg['port']}/{pg['database']} "
          f"tcp={tcp_ok(pg['host'], pg['port'])}")
    print(f"         redis={rd['host']}:{rd['port']} tcp={tcp_ok(rd['host'], rd['port'])}")
    print(f"         rustfs={fs['endpoint']} tcp={tcp_ok(fs_host, fs_port)}")


def main(argv: list[str]) -> int:
    if not argv:
        show_current()
        return 0
    choice = argv[0].lower()
    if choice not in ENVIRONMENTS:
        print(__doc__)
        return 2
    env = ENVIRONMENTS[choice]
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    io.open(CONFIG_PATH, "w", encoding="utf-8", newline="\n").write(render_toml(env))
    print(f"switched to environment {choice.upper()}: {env['label']}")
    show_current()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
