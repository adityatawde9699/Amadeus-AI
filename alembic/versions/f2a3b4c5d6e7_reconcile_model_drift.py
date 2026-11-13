"""reconcile model drift (scheduled_tasks, naive-UTC timestamps, NOT NULLs)

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-13 12:39:09.560660

``alembic check`` reported the ORM models and the migration chain disagreeing.
This brings the database to the models, defensively, because deployed
databases differ (some tables were created by ``Base.metadata.create_all`` at
startup rather than by migrations):

* ``scheduled_tasks`` never had a migration. Created only if absent.
* Older tables used ``TIMESTAMP WITH TIME ZONE``; the models (and every newer
  table, and SQLite) are naive UTC. Converted with ``AT TIME ZONE 'UTC'`` so
  stored instants are preserved as UTC wall-clock time. Only columns that are
  currently ``timestamptz`` are touched.
* Columns the models declare NOT NULL (all have Python defaults) are
  backfilled with that default, then made NOT NULL — only if still nullable.
* ``ix_tasks_status`` is created if missing.
* ``users_username_key`` / ``interaction_logs_uuid_key`` duplicate the unique
  indexes ``ix_users_username`` / ``ix_interaction_logs_uuid``; dropped only
  when that unique index exists, so uniqueness is never lost.

The type/nullability/constraint steps are PostgreSQL-only (SQLite has no
``ALTER COLUMN`` and ignores both distinctions).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column) pairs the models declare as naive DateTime.
TIMESTAMP_COLUMNS: list[tuple[str, str]] = [
    ("calendar_events", "start_time"),
    ("calendar_events", "end_time"),
    ("calendar_events", "created_at"),
    ("calendar_events", "updated_at"),
    ("conversation_summaries", "created_at"),
    ("interaction_logs", "timestamp"),
    ("messages", "timestamp"),
    ("notes", "created_at"),
    ("notes", "updated_at"),
    ("pomodoro_sessions", "started_at"),
    ("pomodoro_sessions", "completed_at"),
    ("pomodoro_sessions", "created_at"),
    ("processed_emails", "processed_at"),
    ("reminders", "time"),
    ("reminders", "created_at"),
    ("tasks", "created_at"),
    ("tasks", "completed_at"),
    ("users", "created_at"),
]

# (table, column, SQL literal of the model's default) for NOT NULL columns.
NOT_NULL_COLUMNS: list[tuple[str, str, str]] = [
    ("conversation_summaries", "messages_summarized", "0"),
    ("pomodoro_sessions", "task_description", "''"),
    ("processed_emails", "subject", "''"),
    ("processed_emails", "sender", "''"),
    ("processed_emails", "action_taken", "'read'"),
]

# (table, redundant unique constraint, unique index that already enforces it)
REDUNDANT_UNIQUE: list[tuple[str, str, str]] = [
    ("users", "users_username_key", "ix_users_username"),
    ("interaction_logs", "interaction_logs_uuid_key", "ix_interaction_logs_uuid"),
]

_STATUS = postgresql.ENUM(
    "pending",
    "running",
    "done",
    "failed",
    "cancelled",
    name="scheduledtaskstatusdb",
    create_type=False,  # created idempotently by d4e5f6a7b8c9
)

SCHEDULED_INDEXES: list[tuple[str, list[str]]] = [
    ("idx_scheduled_status_runat", ["status", "run_at"]),
    ("ix_scheduled_tasks_created_at", ["created_at"]),
    ("ix_scheduled_tasks_executed_at", ["executed_at"]),
    ("ix_scheduled_tasks_id", ["id"]),
    ("ix_scheduled_tasks_run_at", ["run_at"]),
    ("ix_scheduled_tasks_session_id", ["session_id"]),
    ("ix_scheduled_tasks_status", ["status"]),
]


def _columns(insp: sa.Inspector, table: str) -> dict[str, dict]:
    if not insp.has_table(table):
        return {}
    return {c["name"]: c for c in insp.get_columns(table)}


def _index_names(insp: sa.Inspector, table: str) -> set[str]:
    if not insp.has_table(table):
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def _is_timestamptz(column: dict) -> bool:
    return isinstance(column["type"], sa.DateTime) and bool(column["type"].timezone)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    # 1. scheduled_tasks (create_all may already have made it).
    if not insp.has_table("scheduled_tasks"):
        if is_pg:
            op.execute(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'scheduledtaskstatusdb') "
                "THEN CREATE TYPE scheduledtaskstatusdb AS ENUM "
                "('pending','running','done','failed','cancelled'); END IF; END $$;"
            )
        status_type = (
            _STATUS
            if is_pg
            else sa.Enum(
                "pending", "running", "done", "failed", "cancelled", name="scheduledtaskstatusdb"
            )
        )
        op.create_table(
            "scheduled_tasks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("session_id", sa.String(length=256), nullable=False),
            sa.Column("run_at", sa.DateTime(), nullable=False),
            sa.Column("status", status_type, nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("executed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        insp = sa.inspect(bind)
    existing = _index_names(insp, "scheduled_tasks")
    for name, cols in SCHEDULED_INDEXES:
        if name not in existing:
            op.create_index(name, "scheduled_tasks", cols, unique=False)

    # 2. ix_tasks_status
    if insp.has_table("tasks") and "ix_tasks_status" not in _index_names(insp, "tasks"):
        op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)

    if not is_pg:
        return

    # 3. timestamptz -> naive UTC, preserving the instant.
    for table, column in TIMESTAMP_COLUMNS:
        col = _columns(insp, table).get(column)
        if col is not None and _is_timestamptz(col):
            op.alter_column(
                table,
                column,
                type_=sa.DateTime(),
                existing_type=postgresql.TIMESTAMP(timezone=True),
                existing_nullable=col["nullable"],
                postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
            )

    # 4. backfill, then NOT NULL.
    for table, column, default in NOT_NULL_COLUMNS:
        col = _columns(insp, table).get(column)
        if col is not None and col["nullable"]:
            op.execute(f'UPDATE {table} SET "{column}" = {default} WHERE "{column}" IS NULL')
            op.alter_column(table, column, existing_type=col["type"], nullable=False)

    # 5. drop duplicate unique constraints only where the unique index exists.
    for table, constraint, index in REDUNDANT_UNIQUE:
        if not insp.has_table(table):
            continue
        constraints = {uc["name"] for uc in insp.get_unique_constraints(table)}
        unique_indexes = {ix["name"] for ix in insp.get_indexes(table) if ix.get("unique")}
        if constraint in constraints and index in unique_indexes:
            op.drop_constraint(constraint, table, type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        for table, constraint, _index in REDUNDANT_UNIQUE:
            column = "username" if table == "users" else "uuid"
            if constraint not in {uc["name"] for uc in insp.get_unique_constraints(table)}:
                op.create_unique_constraint(constraint, table, [column])
        for table, column, _default in NOT_NULL_COLUMNS:
            col = _columns(insp, table).get(column)
            if col is not None and not col["nullable"]:
                op.alter_column(table, column, existing_type=col["type"], nullable=True)
        for table, column in TIMESTAMP_COLUMNS:
            col = _columns(insp, table).get(column)
            if col is not None and not _is_timestamptz(col):
                op.alter_column(
                    table,
                    column,
                    type_=postgresql.TIMESTAMP(timezone=True),
                    existing_type=sa.DateTime(),
                    existing_nullable=col["nullable"],
                    postgresql_using=f"\"{column}\" AT TIME ZONE 'UTC'",
                )

    if "ix_tasks_status" in _index_names(insp, "tasks"):
        op.drop_index("ix_tasks_status", table_name="tasks")
    # scheduled_tasks is left in place: it may predate this revision (created by
    # create_all) and holds queued work. The enum is owned by d4e5f6a7b8c9.
