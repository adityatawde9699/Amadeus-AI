from fastapi_users import schemas

from src.infra.persistence.orm_models import UserRoleDB


class UserRead(schemas.BaseUser[int]):
    username: str
    role: UserRoleDB
    tenant_id: str | None


class UserCreate(schemas.BaseUserCreate):
    """Public registration payload.

    SECURITY: ``role`` and ``tenant_id`` are intentionally NOT accepted here.
    Allowing them would let anyone self-register as ``admin`` (privilege
    escalation). New users default to ``GUEST`` via the ORM column default;
    role/tenant assignment is an admin/out-of-band operation.
    """

    username: str


class UserUpdate(schemas.BaseUserUpdate):
    """Self-service update payload.

    SECURITY: ``role`` and ``tenant_id`` are NOT accepted — ``PATCH /users/me``
    must never be a privilege-escalation path. Role/tenant changes are performed
    out-of-band through a trusted administrative process.
    """

    username: str | None = None
