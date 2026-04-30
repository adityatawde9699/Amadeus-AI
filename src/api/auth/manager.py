import logging
from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, IntegerIDMixin
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import _get_or_create_secret_key, get_settings
from src.infra.persistence.database import get_db_session
from src.infra.persistence.orm_models import UserORM


logger = logging.getLogger(__name__)


async def get_user_db(
    session: AsyncSession = Depends(get_db_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, UserORM)


class UserManager(IntegerIDMixin, BaseUserManager[UserORM, int]):
    reset_password_token_secret = _get_or_create_secret_key(get_settings())
    verification_token_secret = _get_or_create_secret_key(get_settings())

    async def on_after_register(self, user: UserORM, request: Request | None = None) -> None:
        logger.info("User %s has registered.", user.id)

    async def on_after_forgot_password(
        self, user: UserORM, token: str, request: Request | None = None
    ) -> None:
        logger.info("User %s has forgot their password. Reset token: %s", user.id, token)

    async def on_after_request_verify(
        self, user: UserORM, token: str, request: Request | None = None
    ) -> None:
        logger.info("Verification requested for user %s. Verification token: %s", user.id, token)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="api/v1/auth/jwt/login")


def get_jwt_strategy() -> JWTStrategy:
    settings = get_settings()
    # default lifetime: 24h
    lifetime = getattr(settings, "JWT_EXPIRY_HOURS", 24) * 3600
    return JWTStrategy(secret=_get_or_create_secret_key(settings), lifetime_seconds=lifetime)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[UserORM, int](
    get_user_manager,
    [auth_backend],
)

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
