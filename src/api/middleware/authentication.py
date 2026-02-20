"""
JWT Authentication Middleware for FastAPI.

Validates JWT bearer tokens to secure endpoints.
"""

import logging
from typing import Mapping

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from src.core.config import get_settings


logger = logging.getLogger(__name__)

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
        # Assuming HS256 algorithm by default for JWT
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=["HS256"]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
