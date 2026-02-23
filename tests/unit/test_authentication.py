"""
Unit tests for JWT authentication middleware.

Tests cover:
- Valid token accepted
- Expired token rejected with HTTP 401
- Missing SECRET_KEY returns HTTP 500
- create_access_token produces correctly structured tokens
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key-for-unit-tests-only"
_ALGORITHM = "HS256"


def _make_token(payload: dict) -> str:
    """Encode a raw JWT with the test secret."""
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def _make_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


# ---------------------------------------------------------------------------
# Tests: verify_jwt_token
# ---------------------------------------------------------------------------

class TestVerifyJwtToken:
    def test_valid_token_is_accepted(self):
        """A token with a future `exp` and valid signature is accepted."""
        from src.api.middleware.authentication import verify_jwt_token

        payload = {
            "sub": "user_123",
            "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(tz=timezone.utc),
        }
        token = _make_token(payload)
        creds = _make_credentials(token)

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.is_production = False

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            result = verify_jwt_token(creds)

        assert result["sub"] == "user_123"

    def test_expired_token_raises_401(self):
        """A token whose `exp` is in the past is rejected."""
        from src.api.middleware.authentication import verify_jwt_token

        payload = {
            "sub": "user_expired",
            "exp": datetime.now(tz=timezone.utc) - timedelta(seconds=10),
            "iat": datetime.now(tz=timezone.utc) - timedelta(hours=1),
        }
        token = _make_token(payload)
        creds = _make_credentials(token)

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.is_production = False

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                verify_jwt_token(creds)

        assert exc_info.value.status_code == 401

    def test_wrong_signature_raises_401(self):
        """A token signed with the wrong key is rejected."""
        from src.api.middleware.authentication import verify_jwt_token

        payload = {
            "sub": "attacker",
            "exp": datetime.now(tz=timezone.utc) + timedelta(hours=1),
        }
        token = _make_token_with_secret(payload, "wrong-secret")
        creds = _make_credentials(token)

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.is_production = False

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                verify_jwt_token(creds)

        assert exc_info.value.status_code == 401

    def test_missing_secret_key_raises_500(self):
        """When SECRET_KEY is None the endpoint should return HTTP 500."""
        from src.api.middleware.authentication import verify_jwt_token

        creds = _make_credentials("any.token.here")

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = None
        mock_settings.is_production = False

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                verify_jwt_token(creds)

        assert exc_info.value.status_code == 500

    def test_production_token_without_exp_rejected(self):
        """In production mode a token without `exp` must be rejected."""
        from src.api.middleware.authentication import verify_jwt_token

        # Token has no exp
        payload = {"sub": "user_no_exp"}
        token = _make_token(payload)
        creds = _make_credentials(token)

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.is_production = True

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            with pytest.raises(HTTPException) as exc_info:
                verify_jwt_token(creds)

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: create_access_token
# ---------------------------------------------------------------------------

class TestCreateAccessToken:
    def test_token_contains_sub_exp_iat(self):
        """create_access_token must include sub, exp, and iat claims."""
        from src.api.middleware.authentication import create_access_token

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.JWT_EXPIRY_HOURS = 24  # Must be an int, not a MagicMock

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            token = create_access_token("alice")

        decoded = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert decoded["sub"] == "alice"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_extra_claims_are_present(self):
        """Extra claims passed to create_access_token appear in the token."""
        from src.api.middleware.authentication import create_access_token

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = _SECRET
        mock_settings.JWT_EXPIRY_HOURS = 24  # Must be an int, not a MagicMock

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            token = create_access_token("bob", extra_claims={"role": "admin"})

        decoded = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert decoded["role"] == "admin"

    def test_missing_secret_raises_runtime_error(self):
        """create_access_token raises RuntimeError when SECRET_KEY is missing."""
        from src.api.middleware.authentication import create_access_token

        mock_settings = MagicMock()
        mock_settings.SECRET_KEY = None

        with patch("src.api.middleware.authentication.get_settings", return_value=mock_settings):
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                create_access_token("charlie")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _make_token_with_secret(payload: dict, secret: str) -> str:
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)
