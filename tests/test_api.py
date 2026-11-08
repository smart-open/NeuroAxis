"""API layer tests via TestClient (no live infra needed)."""

from __future__ import annotations

import os
from unittest import mock

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient

from plcagent.api.app import create_app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_infra_shape(client):
    resp = client.get("/api/v1/infra")
    assert resp.status_code == 200
    body = resp.json()
    for service in ("postgres", "redis", "rustfs"):
        assert set(body[service]) == {"ok", "detail"}


def test_verify_ok(client):
    resp = client.post("/api/v1/verify", json={"runs": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["runs"] == 5
    assert len(body["digest"]) == 64


def test_verify_rejects_bad_runs(client):
    resp = client.post("/api/v1/verify", json={"runs": 0})
    assert resp.status_code == 422


def test_api_key_required_when_configured():
    with mock.patch.dict(os.environ, {"PLCAGENT_API_KEY": "secret"}):
        client = TestClient(create_app())
        assert client.get("/api/v1/health").status_code == 401
        ok = client.get("/api/v1/health", headers={"X-API-Key": "secret"})
        assert ok.status_code == 200
    # key removed again: open access
    client = TestClient(create_app())
    assert client.get("/api/v1/health").status_code == 200
