"""Tests for homebase-matter sidecar (stub mode — no real Matter hardware needed)."""
import base64
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import ed25519
from app import create_app
from auth import Auth, key_id, resolve_identity

API_TOKEN = "test-core-api-token"
SEED = bytes([9]) * 32
PUBLIC_KEY = base64.urlsafe_b64encode(ed25519.public_key(SEED)).rstrip(b"=").decode()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def identity(user_id, permission, seed=SEED, ttl=300, now=None, expires=True):
    """An identity token signed the way core signs the ones it forwards:
    Ed25519 over base64url claims that expire."""
    now = int(time.time()) if now is None else now
    pub = ed25519.public_key(seed)
    claims = {"user_id": user_id, "email": user_id + "@test", "permission": permission,
              "iat": now, "max": now + 86400, "kid": key_id(pub)}
    if expires:
        claims["exp"] = now + ttl
    payload = b64(json.dumps(claims).encode())
    return payload + "." + b64(ed25519.sign(seed, payload.encode()))


def legacy_identity(user_id, permission, api_token=API_TOKEN, kid="hmac", ttl=300):
    """A token signed exactly as core signed legacy tokens: HMAC-SHA256 keyed
    with base64std(sha256("localitas-internal-token-v1:" + api_token)), which
    every app can derive from the api_token it holds."""
    now = int(time.time())
    claims = {"email": user_id + "@test", "name": user_id, "user_id": user_id, "permission": permission}
    if kid:
        claims.update({"iat": now, "exp": now + ttl, "max": now + 86400, "kid": kid})
    key = base64.standard_b64encode(hashlib.sha256(f"localitas-internal-token-v1:{api_token}".encode()).digest())
    payload = b64(json.dumps(claims).encode())
    return payload + "." + b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def core():
    """A real HTTP server answering GET /api/auth/identity/public-key as an
    older core did, still offering accept_legacy."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/auth/identity/public-key" or self.headers.get("Authorization") != f"Bearer {API_TOKEN}":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"kid": key_id(ed25519.public_key(SEED)), "public_key": PUBLIC_KEY, "accept_legacy": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def anon(tmp_path):
    app = create_app(storage=str(tmp_path), api_token=API_TOKEN, public_keys=[PUBLIC_KEY])
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
    forged = identity("mallory", "admin", seed=bytes(32))
    payload, _, _ = identity("mallory", "admin").partition(".")
    expired = identity("mallory", "admin", now=int(time.time()) - 3600)
    for headers in ({}, bearer("not-a-token"), bearer(forged), bearer(payload + ".tampered"), bearer(identity("", "admin")),
                    bearer(legacy_identity("mallory", "admin")), bearer(legacy_identity("mallory", "admin", kid="")),
                    bearer(identity("mallory", "admin", expires=False)), bearer(expired)):
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


def test_hmac_tokens_are_refused_even_when_env_and_core_ask_for_legacy(tmp_path, monkeypatch, core):
    monkeypatch.delenv("LOCALITAS_IDENTITY_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LOCALITAS_ACCEPT_LEGACY_IDENTITY_TOKENS", "true")
    keys = resolve_identity(API_TOKEN, core_url=core)
    assert keys == [PUBLIC_KEY]
    app = create_app(storage=str(tmp_path), api_token=API_TOKEN, public_keys=keys)
    with TestClient(app) as c:
        for token in (legacy_identity("mallory", "admin"), legacy_identity("mallory", "admin", kid="")):
            assert c.get("/devices", headers=bearer(token)).status_code == 401
            assert c.post("/commission", json={"setup_code": "MT:Y.K9042C00KA0648G00"}, headers=bearer(token)).status_code == 401
        assert c.get("/devices", headers=bearer(identity("bob", "read"))).status_code == 200
    with pytest.raises(Exception):
        Auth(API_TOKEN, public_keys=keys).caller("Bearer " + legacy_identity("bob", "write"))


def test_tokens_without_expiry_are_refused(tmp_path, monkeypatch, core):
    monkeypatch.delenv("LOCALITAS_IDENTITY_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LOCALITAS_ACCEPT_LEGACY_IDENTITY_TOKENS", "true")
    app = create_app(storage=str(tmp_path), api_token=API_TOKEN, public_keys=resolve_identity(API_TOKEN, core_url=core))
    with TestClient(app) as c:
        assert c.get("/devices", headers=bearer(identity("bob", "admin", expires=False))).status_code == 401
        assert c.get("/devices", headers=bearer(identity("bob", "admin"))).status_code == 200
    with pytest.raises(Exception):
        Auth(API_TOKEN, public_keys=[PUBLIC_KEY]).caller("Bearer " + identity("bob", "read", expires=False))


def test_tokens_expire_after_two_minutes_of_skew():
    auth = Auth(API_TOKEN, public_keys=[PUBLIC_KEY])
    now = int(time.time())
    assert auth.caller("Bearer " + identity("bob", "read", ttl=300, now=now - 300 - 100))["user_id"] == "bob"
    with pytest.raises(Exception):
        auth.caller("Bearer " + identity("bob", "read", ttl=300, now=now - 300 - 140))
    with pytest.raises(Exception):
        auth.caller("Bearer " + identity("bob", "read", now=now + 300))


def test_identity_key_comes_from_env_then_core(monkeypatch, core):
    monkeypatch.setenv("LOCALITAS_IDENTITY_PUBLIC_KEY", PUBLIC_KEY)
    assert resolve_identity(API_TOKEN, core_url="http://127.0.0.1:1") == [PUBLIC_KEY]
    monkeypatch.delenv("LOCALITAS_IDENTITY_PUBLIC_KEY")
    assert resolve_identity(API_TOKEN, core_url=core) == [PUBLIC_KEY]
    assert resolve_identity(API_TOKEN, core_url="http://127.0.0.1:1") == []
