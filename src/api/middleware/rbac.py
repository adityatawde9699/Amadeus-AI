"""
Role-Based Access Control (RBAC) Dependencies.

Inject these dependencies into FastAPI route definitions to securely
restrict access based on the user's role embedded within their JWT token.
"""

import logging

from fastapi import Depends, HTTPException, status

from src.api.middleware.authentication import verify_jwt_token
from src.infra.persistence.orm_models import UserRoleDB


logger = logging.getLogger(__name__)

class RequireRole:
    """
    FastAPI Dependency class to enforce RBAC.

    Usage:
        @app.get("/system-tools", dependencies=[Depends(RequireRole([UserRoleDB.ADMIN]))])
        async def secure_route(): ...
    """
    def __init__(self, allowed_roles: list[UserRoleDB]):
        self.allowed_roles = allowed_roles

    def __call__(self, payload: dict = Depends(verify_jwt_token)) -> dict:
        """
        Extracts the role from the verified JWT payload and checks permissions.
        """
        # Default to GUEST if no role is found in the token
        user_role = payload.get("role", UserRoleDB.GUEST.value)
        user_id = payload.get("sub", "Unknown")

        # Check if the user's role string matches any of the allowed enum values
        if not any(role.value == user_role for role in self.allowed_roles):
            logger.warning(
                f"Unauthorized access attempt by User '{user_id}' (Role: {user_role}). "
                f"Requires one of: {[r.value for r in self.allowed_roles]}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough privileges to perform this action.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug(f"RBAC passed for User '{user_id}' with Role '{user_role}'.")
        return payload

# Shortcut dependency for Admin-only routes
RequireAdmin = RequireRole([UserRoleDB.ADMIN])

# Shortcut dependency for authenticated general users or admins
RequireUser = RequireRole([UserRoleDB.ADMIN, UserRoleDB.USER])
