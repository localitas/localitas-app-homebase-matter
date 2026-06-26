"""Tests for homebase-matter sidecar (stub mode — no real Matter hardware needed)."""
import pytest
from fastapi.testclient import TestClient

from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(storage=str(tmp_path))
    # Run lifespan synchronously for tests
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code in (200, 503)
    assert "ok" in resp.json()


def test_list_devices_empty(client):
    resp = client.get("/devices")
    assert resp.status_code == 200
    assert resp.json() == []


def test_commission_stub(client):
    resp = client.post("/commission", json={"setup_code": "MT:Y.K9042C00KA0648G00"})
    assert resp.status_code == 200
    data = resp.json()
    assert "node_id" in data
    assert "vendor" in data
    assert "clusters" in data


def test_get_device_not_found(client):
    resp = client.get("/devices/99999")
    assert resp.status_code in (404, 500)


def test_send_command_stub(client):
    resp = client.post("/devices/1/command", json={
        "cluster": "OnOff",
        "command": "Toggle",
        "arguments": {},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "success" in data


def test_decommission_stub(client):
    resp = client.delete("/commission/1")
    assert resp.status_code in (200, 404, 500)
