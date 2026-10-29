"""Neon identities verified against the configured branch, with no guest fallback."""

import os
from functools import lru_cache
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, Request


@lru_cache(maxsize=4)
def keys(base_url: str):
    return jwt.PyJWKClient(
        base_url.rstrip("/") + "/.well-known/jwks.json", cache_jwk_set=True, lifespan=300, timeout=5
    )


def identity(request: Request) -> dict | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    if not header.startswith("Bearer ") or not 1 < len(header) < 16384:
        raise HTTPException(401, "Sign in again to continue.")
    base = os.environ.get("NEON_AUTH_BASE_URL", "")
    if not base or urlsplit(base).scheme != "https":
        raise HTTPException(503, "Account sign-in is not configured on this environment.")
    origin = f"https://{urlsplit(base).netloc}"
    token = header[7:]
    try:
        key = keys(base).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            key.key,
            algorithms=["EdDSA"],
            issuer=origin,
            audience=origin,
            leeway=10,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if (
            not isinstance(payload["sub"], str)
            or not 1 <= len(payload["sub"]) <= 128
            or payload.get("banned")
            or payload.get("role") != "authenticated"
        ):
            raise jwt.InvalidTokenError()
        return payload
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(
            503, "Sign-in verification is temporarily unavailable. Retry shortly."
        ) from None
    except jwt.PyJWTError:
        raise HTTPException(401, "Your sign-in has expired. Sign in again.") from None
