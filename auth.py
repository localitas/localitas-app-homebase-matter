"""Request authentication: core's signed identity tokens, or the app token.

Mirrors localitas-go's AuthMiddleware/RequireScope and the Python SDK's
scope.py: an identity token is "payload.signature", base64url JSON claims
signed by core with its Ed25519 key, verified with core's public key
(LOCALITAS_IDENTITY_PUBLIC_KEY, or fetched from core), and expiring (exp,
with two minutes of clock skew). Any other token, including one signed with
a key derived from core's API token or one without an expiry, is refused:
every app holds that token, so such a token would let any app pose as any
user. The homebase app's own background work (the HomeKit bridge) has no
user and calls with the app token itself.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path

import yaml

from fastapi import HTTPException, Request

import ed25519

_KID_PREFIX = "ed25519-"
_CLOCK_SKEW = 120
_RANK = {"admin": 3, "write": 2, "read": 1, "": 0}


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def key_id(public_key: bytes) -> str:
    """Name an identity public key as core does."""
    return _KID_PREFIX + base64.urlsafe_b64encode(hashlib.sha256(public_key).digest()[:9]).rstrip(b"=").decode()


def _unauthorized():
    return HTTPException(status_code=401, detail="authorization required")


class Auth:
    def __init__(self, api_token: str, public_keys=()):
        if not api_token:
            raise ValueError("an API token is required to verify requests")
        self._api_token = api_token
        self._public_keys = {}
        for k in public_keys:
            if k:
                raw = _b64url_decode(k.strip())
                self._public_keys[key_id(raw)] = raw

    def caller(self, authorization: str) -> dict:
        """The caller's claims, or HTTPException 401 when the request does
        not prove who it is."""
        if not authorization or not authorization.startswith("Bearer "):
            raise _unauthorized()
        token = authorization[len("Bearer "):]
        if hmac.compare_digest(token.encode(), self._api_token.encode()):
            return {"user_id": "", "permission": "admin", "system": True}
        payload, sep, sig = token.partition(".")
        if not sep or not payload or not sig:
            raise _unauthorized()
        try:
            claims = json.loads(_b64url_decode(payload))
            raw_sig = _b64url_decode(sig)
        except ValueError:
            raise _unauthorized()
        if not isinstance(claims, dict) or not claims.get("user_id"):
            raise _unauthorized()
        kid = claims.get("kid") or ""
        if not kid.startswith(_KID_PREFIX):
            raise _unauthorized()
        pub = self._public_keys.get(kid)
        if pub is None or not ed25519.verify(pub, payload.encode(), raw_sig):
            raise _unauthorized()
        exp = int(claims.get("exp") or 0)
        if not exp:
            raise _unauthorized()
        now = time.time()
        if now > exp + _CLOCK_SKEW or int(claims.get("iat") or 0) > now + _CLOCK_SKEW:
            raise _unauthorized()
        return claims

    def require(self, scope: str):
        """A FastAPI dependency admitting callers with at least scope."""
        def check(request: Request) -> dict:
            claims = self.caller(request.headers.get("authorization", ""))
            if _RANK.get(claims.get("permission", ""), 0) < _RANK[scope]:
                raise HTTPException(status_code=403, detail="insufficient permission")
            return claims
        return check


DEFAULT_CORE_URL = "http://localhost:8090"


def resolve_core_url(core_url: str = "") -> str:
    """Where core is: core_url, else $CORE_URL, else core's default port."""
    return (core_url or os.environ.get("CORE_URL") or DEFAULT_CORE_URL).rstrip("/")


def resolve_identity(api_token: str, core_url: str = "") -> list:
    """The public keys identity tokens verify with:
    LOCALITAS_IDENTITY_PUBLIC_KEY, else what core serves at
    GET /api/auth/identity/public-key, else none."""
    keys = [k for k in os.environ.get("LOCALITAS_IDENTITY_PUBLIC_KEY", "").split(",") if k.strip()]
    if keys:
        return keys
    req = urllib.request.Request(resolve_core_url(core_url) + "/api/auth/identity/public-key", headers={"Authorization": f"Bearer {api_token}"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode())
        if body.get("public_key"):
            return [body["public_key"]]
    except Exception:
        pass
    return []


def resolve_token(flag: str = "", config_path: Path = None) -> str:
    """The core API token to verify callers with: the --token flag, then
    $LOCALITAS_API_TOKEN, then core.auth.api_token in core's config file
    (~/.localitas/config-core.yaml, as the localitas SDKs read it)."""
    if flag:
        return flag
    if os.environ.get("LOCALITAS_API_TOKEN"):
        return os.environ["LOCALITAS_API_TOKEN"]
    path = config_path or Path.home() / ".localitas" / "config-core.yaml"
    if not path.exists():
        return ""
    cfg = yaml.safe_load(path.read_text()) or {}
    return str(((cfg.get("core") or {}).get("auth") or {}).get("api_token") or "")
