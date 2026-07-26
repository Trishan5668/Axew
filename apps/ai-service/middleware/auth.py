"""Supabase JWT verification dependency for FastAPI.

Applied to all payment routes and to /opusclip/process. Two key flavors are
supported transparently:

  - **Symmetric (HS256)** — the legacy default. The project JWT secret is
    set via SUPABASE_JWT_SECRET and used directly.
  - **Asymmetric (ES256 / RS256)** — for projects migrated to Supabase's
    new asymmetric signing keys. The public keys are fetched from
    `${SUPABASE_URL}/auth/v1/.well-known/jwks.json` and cached in memory
    for 60 minutes (rotating once a key roll is detected).

On any failure we raise HTTPException(401) — never fall through silently.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, status

try:
    from jose import JWTError, jwt
except ImportError as exc:  # pragma: no cover - hard dep, surfaced at startup
    raise RuntimeError(
        "python-jose is required for Supabase JWT verification. "
        "Install with: pip install 'python-jose[cryptography]'"
    ) from exc

from .cloud_config import CloudConfigError, cloud_settings

logger = logging.getLogger(__name__)

_SYMMETRIC_ALGORITHMS = ("HS256",)
_ASYMMETRIC_ALGORITHMS = ("ES256", "RS256")
_JWKS_CACHE_TTL_SECONDS = 3600
_JWKS_FETCH_TIMEOUT_SECONDS = 5.0

_jwks_cache: dict[str, Any] = {}  # {url: {"fetched_at": float, "keys": dict[kid, jwk]}}
_jwks_lock = threading.Lock()


def reset_jwks_cache() -> None:
    """Test-only helper to clear the cached JWKS between specs."""
    with _jwks_lock:
        _jwks_cache.clear()


def _fetch_jwks(jwks_url: str, force: bool = False) -> dict[str, dict[str, Any]]:
    """Return {kid -> JWK dict} for the given JWKS URL.

    Uses a TTL cache plus a force-refresh path so a key rotation is picked
    up on the next request (instead of after the TTL elapses).
    """
    now = time.time()
    with _jwks_lock:
        cached = _jwks_cache.get(jwks_url)
        if not force and cached and now - cached["fetched_at"] < _JWKS_CACHE_TTL_SECONDS:
            return cached["keys"]

    try:
        resp = httpx.get(jwks_url, timeout=_JWKS_FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch JWKS from %s: %s", jwks_url, exc)
        raise

    keys_by_kid: dict[str, dict[str, Any]] = {}
    for jwk in payload.get("keys", []):
        kid = jwk.get("kid")
        if kid:
            keys_by_kid[kid] = jwk

    with _jwks_lock:
        _jwks_cache[jwks_url] = {"fetched_at": now, "keys": keys_by_kid}
    return keys_by_kid


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    email: str
    role: str
    raw_claims: dict


def _credentials_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _supabase_jwks_url() -> str | None:
    """Derive the JWKS URL from the Supabase project URL."""
    base = cloud_settings().supabase_url
    if not base:
        return None
    return f"{base.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _decode_token(token: str) -> dict[str, Any]:
    """Decode + verify a Supabase JWT, choosing HS256 or asymmetric path."""
    settings = cloud_settings()

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise _credentials_error("Token header is malformed.") from exc

    alg = header.get("alg")
    if alg in _SYMMETRIC_ALGORITHMS:
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="HS256 token received but SUPABASE_JWT_SECRET is not set.",
            )
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=list(_SYMMETRIC_ALGORITHMS),
            audience="authenticated",
        )

    if alg in _ASYMMETRIC_ALGORITHMS:
        jwks_url = _supabase_jwks_url()
        if not jwks_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Asymmetric JWT received but SUPABASE_URL is not set.",
            )
        kid = header.get("kid")
        if not kid:
            raise _credentials_error("Token header is missing key id (kid).")

        # First try the cached JWKS; on miss, force-refresh exactly once in
        # case the project rotated keys.
        keys = _fetch_jwks(jwks_url)
        jwk = keys.get(kid)
        if not jwk:
            keys = _fetch_jwks(jwks_url, force=True)
            jwk = keys.get(kid)
        if not jwk:
            raise _credentials_error(
                "Token was signed with an unknown key. Please sign in again.",
            )
        return jwt.decode(
            token,
            jwk,
            algorithms=[alg],
            audience="authenticated",
        )

    raise _credentials_error(f"Unsupported token algorithm: {alg!r}")


async def verify_supabase_jwt(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    """FastAPI dependency: decode + validate a Supabase-issued JWT.

    Raises HTTPException(401) on missing / malformed / expired / mis-signed
    tokens. Never returns None.
    """
    settings = cloud_settings()
    if not settings.supabase_jwt_secret and not settings.supabase_url:
        # Cloud is misconfigured server-side. Surface that explicitly instead
        # of pretending the credentials were wrong.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cloud auth is not configured. Set SUPABASE_JWT_SECRET (HS256) "
                "or SUPABASE_URL (asymmetric/JWKS)."
            ),
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise _credentials_error("Missing bearer token. Sign in to continue.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise _credentials_error("Empty bearer token.")

    try:
        claims = _decode_token(token)
    except HTTPException:
        raise
    except JWTError as exc:
        logger.info("Rejected JWT: %s", exc)
        raise _credentials_error(
            "Your session is invalid or has expired. Please sign in again.",
        ) from exc

    sub = claims.get("sub")
    email = claims.get("email") or ""
    role = claims.get("role", "authenticated")

    if not sub:
        raise _credentials_error("Token is missing the user id (sub).")

    try:
        user_id = UUID(sub)
    except (TypeError, ValueError) as exc:
        raise _credentials_error("Token sub is not a valid user id.") from exc

    return AuthenticatedUser(user_id=user_id, email=email, role=role, raw_claims=claims)


# Type alias for use in route signatures
CurrentUser = Annotated[AuthenticatedUser, Depends(verify_supabase_jwt)]
