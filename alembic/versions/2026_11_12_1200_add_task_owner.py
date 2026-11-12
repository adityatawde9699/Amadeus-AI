"""add tasks.owner_id (per-user task tenancy)

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-11-12 12:00:00.000000

Before this, every authenticated REST user could list, complete and delete every
other user's tasks (audit finding H-4). Existing rows keep ``owner_id = NULL``
(unowned) and stay visible only to admins and the agent's own task tools.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_owner_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(c["name"] == "owner_id" for c in inspector.get_columns("tasks"))


def upgrade() -> None:
    # Idempotent: startup also runs Base.metadata.create_all, so a database built
    # that way (RUN_MIGRATIONS_ON_START=false) may already have the column.
    if _has_owner_column():
        return
    # batch mode so the FK is added correctly on SQLite as well as PostgreSQL.
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch.create_index("ix_tasks_owner_id", ["owner_id"])
        batch.create_foreign_key(
            "fk_tasks_owner_id_users", "users", ["owner_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_owner_id_users", type_="foreignkey")
        batch.drop_index("ix_tasks_owner_id")
        batch.drop_column("owner_id")
