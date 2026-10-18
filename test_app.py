"""Tests for homebase-matter sidecar (stub mode — no real Matter hardware needed)."""
import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import create_app

API_TOKEN = "test-core-api-token"


def identity(user_id, permission, api_token=API_TOKEN):
    """An identity token signed the way core signs the ones it forwards."""
    key = base64.standard_b64encode(hashlib.sha256(f"localitas-internal-token-v1:{api_token}".encode()).digest())
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": user_id, "email": user_id + "@test", "permission": permission}).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{payload}.{sig}"


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def anon(tmp_path):
    app = create_app(storage=str(tmp_path), api_token=API_TOKEN)
    # Run lifespan synchronously for tests
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(anon):
    anon.headers.update(bearer(identity("alice", "write")))
    yield anon


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


PROTECTED = [
    ("get", "/devices", None, "read"),
    ("get", "/devices/1", None, "read"),
    ("post", "/commission", {"setup_code": "MT:Y.K9042C00KA0648G00"}, "write"),
    ("delete", "/commission/1", None, "write"),
    ("post", "/devices/1/command", {"cluster": "OnOff", "command": "Toggle", "arguments": {}}, "write"),
]


def call(c, method, path, body, headers):
    if body is None:
        return getattr(c, method)(path, headers=headers)
    return getattr(c, method)(path, json=body, headers=headers)


@pytest.mark.parametrize("method,path,body,scope", PROTECTED)
def test_callers_who_do_not_prove_who_they_are_are_refused(anon, method, path, body, scope):
    forged = identity("mallory", "admin", api_token="some-other-token")
    payload, _, _ = identity("mallory", "admin").partition(".")
    for headers in ({}, bearer("not-a-token"), bearer(forged), bearer(payload + ".tampered"), bearer(identity("", "admin"))):
        resp = call(anon, method, path, body, headers)
        assert resp.status_code == 401, (headers, resp.status_code)


@pytest.mark.parametrize("method,path,body,scope", PROTECTED)
def test_scope_is_enforced(anon, method, path, body, scope):
    read_resp = call(anon, method, path, body, bearer(identity("bob", "read")))
    if scope == "write":
        assert read_resp.status_code == 403
    else:
        assert read_resp.status_code != 403
    assert call(anon, method, path, body, bearer(identity("bob", "guest"))).status_code == 403


@pytest.mark.parametrize("method,path,body,scope", PROTECTED)
def test_the_homebase_app_token_is_admitted(anon, method, path, body, scope):
    resp = call(anon, method, path, body, bearer(API_TOKEN))
    assert resp.status_code not in (401, 403)


def test_health_needs_no_token(anon):
    assert anon.get("/health").status_code in (200, 503)


def test_refuses_to_start_without_a_token(tmp_path):
    with pytest.raises(ValueError):
        create_app(storage=str(tmp_path), api_token="")


def test_token_comes_from_flag_env_then_core_config(tmp_path, monkeypatch):
    from auth import resolve_token
    cfg = tmp_path / "config-core.yaml"
    cfg.write_text("core:\n  auth:\n    api_token: from-core-config\n")
    monkeypatch.delenv("LOCALITAS_API_TOKEN", raising=False)
    assert resolve_token("", cfg) == "from-core-config"
    monkeypatch.setenv("LOCALITAS_API_TOKEN", "from-env")
    assert resolve_token("", cfg) == "from-env"
    assert resolve_token("from-flag", cfg) == "from-flag"
    monkeypatch.delenv("LOCALITAS_API_TOKEN")
    assert resolve_token("", tmp_path / "missing.yaml") == ""
