from fastapi_users import schemas

from src.infra.persistence.orm_models import UserRoleDB


class UserRead(schemas.BaseUser[int]):
    username: str
    role: UserRoleDB
    tenant_id: str | None


class UserCreate(schemas.BaseUserCreate):
    username: str
    role: UserRoleDB = UserRoleDB.GUEST
    tenant_id: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    username: str | None = None
    role: UserRoleDB | None = None
    tenant_id: str | None = None
