"""Request authentication: core's signed identity tokens, or the app token.

Mirrors localitas-go's AuthMiddleware/RequireScope and the Python SDK's
scope.py: an identity token is "payload.signature", base64url JSON claims
signed with HMAC-SHA256 under a key derived from core's API token. The
homebase app's own background work (the HomeKit bridge) has no user and
calls with the app token itself.
"""
import base64
import hashlib
import hmac
import json

from fastapi import HTTPException, Request

_KEY_DOMAIN = "localitas-internal-token-v1"
_RANK = {"admin": 3, "write": 2, "read": 1, "": 0}


class Auth:
    def __init__(self, api_token: str):
        if not api_token:
            raise ValueError("an API token is required to verify requests")
        self._api_token = api_token
        digest = hashlib.sha256(f"{_KEY_DOMAIN}:{api_token}".encode()).digest()
        self._key = base64.standard_b64encode(digest)

    def caller(self, authorization: str) -> dict:
        """The caller's claims, or HTTPException 401 when the request does
        not prove who it is."""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="authorization required")
        token = authorization[len("Bearer "):]
        if hmac.compare_digest(token.encode(), self._api_token.encode()):
            return {"user_id": "", "permission": "admin", "system": True}
        payload, sep, sig = token.partition(".")
        if not sep or not payload or not sig:
            raise HTTPException(status_code=401, detail="authorization required")
        expected = base64.urlsafe_b64encode(hmac.new(self._key, payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="authorization required")
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except ValueError:
            raise HTTPException(status_code=401, detail="authorization required")
        if not isinstance(claims, dict) or not claims.get("user_id"):
            raise HTTPException(status_code=401, detail="authorization required")
        return claims

    def require(self, scope: str):
        """A FastAPI dependency admitting callers with at least scope."""
        def check(request: Request) -> dict:
            claims = self.caller(request.headers.get("authorization", ""))
            if _RANK.get(claims.get("permission", ""), 0) < _RANK[scope]:
                raise HTTPException(status_code=403, detail="insufficient permission")
            return claims
        return check
