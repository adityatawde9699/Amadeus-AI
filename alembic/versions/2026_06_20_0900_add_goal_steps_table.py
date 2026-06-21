"""add goal_steps table (Phase 2 — durable long-horizon goals)

Revision ID: d4e5f6a7b8c9
Revises: c9f31d0a7b42
Create Date: 2026-06-20 09:00:00.000000

Persists the agent's goal plan as ordered, statused steps so a multi-step goal
can be resumed after a restart. Reuses the existing ``scheduledtaskstatusdb``
enum (pending/running/done/failed/cancelled) rather than introducing a new one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c9f31d0a7b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS = sa.Enum(
    "pending", "running", "done", "failed", "cancelled",
    name="scheduledtaskstatusdb",
)


def upgrade() -> None:
    bind = op.get_bind()
    # The scheduled_tasks table (Phase 0) created this enum via create_all on
    # some deployments; make creation idempotent on PostgreSQL.
    status_type = _STATUS
    if bind.dialect.name == "postgresql":
        status_type = sa.Enum(
            "pending", "running", "done", "failed", "cancelled",
            name="scheduledtaskstatusdb",
            create_type=False,
        )
        op.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'scheduledtaskstatusdb') "
            "THEN CREATE TYPE scheduledtaskstatusdb AS ENUM "
            "('pending','running','done','failed','cancelled'); END IF; END $$;"
        )

    op.create_table(
        "goal_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("expert", sa.String(length=64), nullable=True),
        sa.Column("subtask", sa.Text(), nullable=False),
        sa.Column("status", status_type, nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goal_steps_id"), "goal_steps", ["id"], unique=False)
    op.create_index(op.f("ix_goal_steps_goal_id"), "goal_steps", ["goal_id"], unique=False)
    op.create_index(op.f("ix_goal_steps_seq"), "goal_steps", ["seq"], unique=False)
    op.create_index(op.f("ix_goal_steps_status"), "goal_steps", ["status"], unique=False)
    op.create_index(op.f("ix_goal_steps_created_at"), "goal_steps", ["created_at"], unique=False)
    op.create_index(op.f("ix_goal_steps_completed_at"), "goal_steps", ["completed_at"], unique=False)
    op.create_index("idx_goal_step_goal_status", "goal_steps", ["goal_id", "status"], unique=False)
    op.create_index("idx_goal_step_goal_seq", "goal_steps", ["goal_id", "seq"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_goal_step_goal_seq", table_name="goal_steps")
    op.drop_index("idx_goal_step_goal_status", table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_completed_at"), table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_created_at"), table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_status"), table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_seq"), table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_goal_id"), table_name="goal_steps")
    op.drop_index(op.f("ix_goal_steps_id"), table_name="goal_steps")
    op.drop_table("goal_steps")
