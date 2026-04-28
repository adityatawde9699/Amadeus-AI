"""
Role-Based Access Control (RBAC) Dependencies.

Inject these dependencies into FastAPI route definitions to securely
restrict access based on the user's role embedded within their database object.
"""

import logging

from fastapi import Depends, HTTPException, status

from src.api.auth.manager import current_active_user
from src.infra.persistence.orm_models import UserORM, UserRoleDB


logger = logging.getLogger(__name__)


class RequireRole:
    """
    FastAPI Dependency class to enforce RBAC using FastAPI-Users.

    Usage:
        @app.get("/system-tools", dependencies=[Depends(RequireRole([UserRoleDB.ADMIN]))])
        async def secure_route(): ...
    """

    def __init__(self, allowed_roles: list[UserRoleDB]):
        self.allowed_roles = allowed_roles

    def __call__(self, user: UserORM = Depends(current_active_user)) -> UserORM:
        """
        Extracts the role from the UserORM object and checks permissions.
        """
        # Check if the user's role string matches any of the allowed enum values
        if not any(role.value == user.role for role in self.allowed_roles):
            logger.warning(
                f"Unauthorized access attempt by User '{user.id}' (Role: {user.role}). "
                f"Requires one of: {[r.value for r in self.allowed_roles]}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough privileges to perform this action.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.debug("RBAC passed for User '%s' with Role '%s'.", user.id, user.role)
        return user


# Shortcut dependency for Admin-only routes
RequireAdmin = RequireRole([UserRoleDB.ADMIN])

# Shortcut dependency for authenticated general users or admins
RequireUser = RequireRole([UserRoleDB.ADMIN, UserRoleDB.USER])
