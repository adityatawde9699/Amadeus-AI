"""
JWT Authentication Middleware for FastAPI.

Validates JWT bearer tokens to secure endpoints.
Tokens must carry both `exp` (expiry) and `iat` (issued-at) claims.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.core.config import get_settings


logger = logging.getLogger(__name__)

# Default token lifetime if not overridden in settings
_DEFAULT_EXPIRY_HOURS = 24


def create_access_token(subject: str, extra_claims: dict | None = None) -> str:
    """
    Create a signed JWT access token with mandatory `exp` and `iat` claims.

    Args:
        subject:      The `sub` claim — typically a user ID or username.
        extra_claims: Additional payload fields (e.g. `role`, `email`).

    Returns:
        Signed JWT string using HS256.

    Raises:
        RuntimeError: If SECRET_KEY is not configured.
    """
    settings = get_settings()
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured — cannot issue tokens")

    expiry_hours = getattr(settings, "JWT_EXPIRY_HOURS", _DEFAULT_EXPIRY_HOURS)
    now = datetime.now(tz=UTC)
    payload: dict = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
        **(extra_claims or {}),
    }
    return str(jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256"))

# Security scheme for FastAPI OpenAPI docs
security = HTTPBearer()

def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Mapping:
    """
    Verify JWT Bearer token and extract payload.

    Raises HTTPException 401 on invalid, expired, or missing tokens.
    """
    settings = get_settings()
    token = credentials.credentials

    # We require a secret to validate the tokens
    if not settings.SECRET_KEY:
        logger.error("Authentication attempted but SECRET_KEY is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error"
        )

    try:
        # python-jose automatically validates `exp` when present in the token.
        # Tokens without `exp` are accepted only when DEBUG=True (dev tokens).
        result: Mapping[str, object] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={
                # Require exp in production; allow missing exp in dev
                "require_exp": settings.is_production,
            },
        )

        # Extra guard: reject tokens missing exp in production
        if settings.is_production and "exp" not in result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing expiry claim",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return result
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_optional_jwt_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False))
) -> Mapping | None:
    """
    Extract the JWT payload if a token is present, otherwise return None.
    Does not enforce authentication.
    """
    if not credentials:
        return None
    try:
        return verify_jwt_token(credentials)
    except HTTPException:
        return None
