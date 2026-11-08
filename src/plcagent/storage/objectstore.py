"""RustFS object storage access via S3-compatible boto3 client (8.3)."""

from __future__ import annotations

from plcagent.config import RustFsConfig


def client(config: RustFsConfig):
    """Create a boto3 S3 client pointed at RustFS."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "boto3 not installed; run: pip install 'plcagent[infra]'") from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        config=Config(connect_timeout=5, retries={"max_attempts": 1}),
        region_name="us-east-1",
    )


def check(config: RustFsConfig) -> tuple[bool, str]:
    """head_bucket probe on the endpoint root. Returns (ok, detail)."""
    try:
        conn = client(config)
        conn.list_buckets()
        return True, f"{config.endpoint_url} ok"
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
