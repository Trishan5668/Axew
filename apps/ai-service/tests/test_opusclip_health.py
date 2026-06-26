"""Tests for the OpusClip health endpoint (GET /opusclip/health).

These build a minimal FastAPI app that mounts only the opusclip router so the
suite stays fast and free of the heavy AI-service startup dependencies.
"""

import os
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure `config` and `routers` resolve regardless of the pytest invocation cwd.
_SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

from config import settings  # noqa: E402
from routers import opusclip  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(opusclip.router, prefix="/opusclip")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_settings():
    original = settings.opusclip_api_key
    yield
    settings.opusclip_api_key = original


def test_health_api_key_missing(client, monkeypatch):
    settings.opusclip_api_key = ""
    resp = client.get("/opusclip/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "offline"
    assert body["service"] == "opusclip"
    assert body["api_key_present"] is False
    assert body["reason"] == "missing_api_key"


def test_health_api_key_present_and_reachable(client, monkeypatch):
    settings.opusclip_api_key = "secret-key-123"

    async def fake_probe(api_key, base_url, timeout):
        return True, None

    monkeypatch.setattr(opusclip, "check_opusclip_reachable", fake_probe)

    resp = client.get("/opusclip/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "online"
    assert body["api_key_present"] is True
    assert body["reason"] is None


def test_health_backend_unavailable(client, monkeypatch):
    settings.opusclip_api_key = "secret-key-123"

    async def fake_probe(api_key, base_url, timeout):
        return False, "backend_unreachable"

    monkeypatch.setattr(opusclip, "check_opusclip_reachable", fake_probe)

    resp = client.get("/opusclip/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "offline"
    assert body["api_key_present"] is True
    assert body["reason"] == "backend_unreachable"


def test_health_authentication_failed(client, monkeypatch):
    settings.opusclip_api_key = "bad-key"

    async def fake_probe(api_key, base_url, timeout):
        return False, "authentication_failed"

    monkeypatch.setattr(opusclip, "check_opusclip_reachable", fake_probe)

    resp = client.get("/opusclip/health")
    body = resp.json()
    assert body["status"] == "offline"
    assert body["reason"] == "authentication_failed"


def test_health_never_exposes_api_key(client, monkeypatch):
    secret = "super-secret-opusclip-key-XYZ"
    settings.opusclip_api_key = secret

    async def fake_probe(api_key, base_url, timeout):
        return True, None

    monkeypatch.setattr(opusclip, "check_opusclip_reachable", fake_probe)

    resp = client.get("/opusclip/health")
    assert secret not in resp.text


def test_health_returns_quickly_even_if_probe_hangs(client, monkeypatch):
    """A misbehaving probe must not block the endpoint beyond the hard cap."""
    settings.opusclip_api_key = "secret-key-123"
    settings.opusclip_health_timeout_sec = 0.3

    import asyncio

    async def hanging_probe(api_key, base_url, timeout):
        await asyncio.sleep(5)
        return True, None

    monkeypatch.setattr(opusclip, "check_opusclip_reachable", hanging_probe)

    start = time.time()
    resp = client.get("/opusclip/health")
    elapsed = time.time() - start

    assert elapsed < 1.0
    body = resp.json()
    assert body["status"] == "offline"
    assert body["api_key_present"] is True
