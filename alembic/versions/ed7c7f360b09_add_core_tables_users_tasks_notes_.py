"""add_core_tables_users_tasks_notes_reminders_calendar_messages_kg

Creates the 9 ORM tables that were missing from the initial migration chain.
The empty baseline (e67531817cd9) relied on Base.metadata.create_all() at
startup — this migration makes those tables first-class Alembic citizens.

Idempotent: each table is checked via sa.inspect() before creation, so
running this on a dev database where create_all() already ran is safe.

Revision ID: ed7c7f360b09
Revises: 8b924c237530
Create Date: 2026-04-30 15:58:25.573973

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ed7c7f360b09"
down_revision: str | Sequence[str] | None = "8b924c237530"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create 9 missing core tables (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # ── users ────────────────────────────────────────────────────────────
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("username", sa.String(50), nullable=False),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("hashed_password", sa.String(1024), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column(
                "role",
                sa.Enum("admin", "user", "guest", name="userroledb"),
                nullable=False,
                server_default="guest",
            ),
            sa.Column("tenant_id", sa.String(36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("username"),
        )
        op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
        op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
        op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)

    # ── tasks ────────────────────────────────────────────────────────────
    if "tasks" not in existing:
        op.create_table(
            "tasks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Enum("pending", "completed", name="taskstatusdb"),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_tasks_id"), "tasks", ["id"], unique=False)
        op.create_index(op.f("ix_tasks_created_at"), "tasks", ["created_at"], unique=False)
        op.create_index(op.f("ix_tasks_completed_at"), "tasks", ["completed_at"], unique=False)
        op.create_index("idx_task_status_created", "tasks", ["status", "created_at"], unique=False)
        op.create_index("idx_task_status_completed", "tasks", ["status", "completed_at"], unique=False)

    # ── notes ────────────────────────────────────────────────────────────
    if "notes" not in existing:
        op.create_table(
            "notes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags", sa.String(512), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_notes_id"), "notes", ["id"], unique=False)
        op.create_index(op.f("ix_notes_title"), "notes", ["title"], unique=False)
        op.create_index(op.f("ix_notes_tags"), "notes", ["tags"], unique=False)
        op.create_index(op.f("ix_notes_created_at"), "notes", ["created_at"], unique=False)
        op.create_index(op.f("ix_notes_updated_at"), "notes", ["updated_at"], unique=False)
        op.create_index("idx_note_tags_created", "notes", ["tags", "created_at"], unique=False)
        op.create_index("idx_note_created_desc", "notes", ["created_at"], unique=False)

    # ── reminders ────────────────────────────────────────────────────────
    if "reminders" not in existing:
        op.create_table(
            "reminders",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.Enum("active", "completed", "cancelled", name="reminderstatusdb"),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_reminders_id"), "reminders", ["id"], unique=False)
        op.create_index(op.f("ix_reminders_time"), "reminders", ["time"], unique=False)
        op.create_index(op.f("ix_reminders_status"), "reminders", ["status"], unique=False)
        op.create_index(op.f("ix_reminders_created_at"), "reminders", ["created_at"], unique=False)
        op.create_index("idx_reminder_status_created", "reminders", ["status", "created_at"], unique=False)
        op.create_index("idx_reminder_status_time", "reminders", ["status", "time"], unique=False)

    # ── calendar_events ──────────────────────────────────────────────────
    if "calendar_events" not in existing:
        op.create_table(
            "calendar_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
            sa.Column("location", sa.String(256), nullable=False, server_default=""),
            sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("recurrence", sa.String(64), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.Enum("active", "cancelled", "completed", name="eventstatusdb"),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_calendar_events_id"), "calendar_events", ["id"], unique=False)
        op.create_index(op.f("ix_calendar_events_start_time"), "calendar_events", ["start_time"], unique=False)
        op.create_index(op.f("ix_calendar_events_end_time"), "calendar_events", ["end_time"], unique=False)
        op.create_index(op.f("ix_calendar_events_status"), "calendar_events", ["status"], unique=False)
        op.create_index(op.f("ix_calendar_events_created_at"), "calendar_events", ["created_at"], unique=False)
        op.create_index("idx_event_start_status", "calendar_events", ["start_time", "status"], unique=False)
        op.create_index("idx_event_date_range", "calendar_events", ["start_time", "end_time"], unique=False)
        op.create_index("idx_event_status_created", "calendar_events", ["status", "created_at"], unique=False)

    # ── interaction_logs ─────────────────────────────────────────────────
    if "interaction_logs" not in existing:
        op.create_table(
            "interaction_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("uuid", sa.String(36), nullable=False),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("interaction_type", sa.String(32), nullable=False, server_default="conversation"),
            sa.Column("input_text", sa.Text(), nullable=False),
            sa.Column("response_text", sa.Text(), nullable=True),
            sa.Column("intent_detected", sa.String(128), nullable=True),
            sa.Column("tool_used", sa.String(128), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("execution_time_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("uuid"),
        )
        op.create_index(op.f("ix_interaction_logs_id"), "interaction_logs", ["id"], unique=False)
        op.create_index(op.f("ix_interaction_logs_uuid"), "interaction_logs", ["uuid"], unique=True)
        op.create_index(op.f("ix_interaction_logs_timestamp"), "interaction_logs", ["timestamp"], unique=False)
        op.create_index(op.f("ix_interaction_logs_source"), "interaction_logs", ["source"], unique=False)
        op.create_index(op.f("ix_interaction_logs_intent_detected"), "interaction_logs", ["intent_detected"], unique=False)
        op.create_index(op.f("ix_interaction_logs_tool_used"), "interaction_logs", ["tool_used"], unique=False)
        op.create_index(op.f("ix_interaction_logs_success"), "interaction_logs", ["success"], unique=False)
        op.create_index("idx_log_source_timestamp", "interaction_logs", ["source", "timestamp"], unique=False)
        op.create_index("idx_log_intent_timestamp", "interaction_logs", ["intent_detected", "timestamp"], unique=False)

    # ── messages ─────────────────────────────────────────────────────────
    if "messages" not in existing:
        op.create_table(
            "messages",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("session_id", sa.String(36), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tool_used", sa.String(128), nullable=True),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_messages_id"), "messages", ["id"], unique=False)
        op.create_index(op.f("ix_messages_session_id"), "messages", ["session_id"], unique=False)
        op.create_index(op.f("ix_messages_tool_used"), "messages", ["tool_used"], unique=False)
        op.create_index(op.f("ix_messages_timestamp"), "messages", ["timestamp"], unique=False)
        op.create_index("idx_message_session_timestamp", "messages", ["session_id", "timestamp"], unique=False)
        op.create_index("idx_message_role_timestamp", "messages", ["role", "timestamp"], unique=False)

    # ── graph_entities ───────────────────────────────────────────────────
    if "graph_entities" not in existing:
        op.create_table(
            "graph_entities",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(256), nullable=False),
            sa.Column("entity_type", sa.String(64), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_graph_entities_name"), "graph_entities", ["name"], unique=False)
        op.create_index(op.f("ix_graph_entities_entity_type"), "graph_entities", ["entity_type"], unique=False)
        op.create_index("idx_entity_name_type", "graph_entities", ["name", "entity_type"], unique=False)

    # ── graph_relationships ──────────────────────────────────────────────
    if "graph_relationships" not in existing:
        op.create_table(
            "graph_relationships",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            sa.Column("predicate", sa.String(128), nullable=False),
            sa.Column("object_id", sa.Integer(), nullable=False),
            sa.Column("strength", sa.Integer(), nullable=False, server_default=sa.text("1")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_graph_relationships_subject_id"), "graph_relationships", ["subject_id"], unique=False)
        op.create_index(op.f("ix_graph_relationships_predicate"), "graph_relationships", ["predicate"], unique=False)
        op.create_index(op.f("ix_graph_relationships_object_id"), "graph_relationships", ["object_id"], unique=False)
        op.create_index("idx_rel_triple", "graph_relationships", ["subject_id", "predicate", "object_id"], unique=False)
        op.create_index("idx_rel_predicate", "graph_relationships", ["predicate"], unique=False)


def downgrade() -> None:
    """Drop all 9 core tables."""
    for table in [
        "graph_relationships", "graph_entities", "messages",
        "interaction_logs", "calendar_events", "reminders",
        "notes", "tasks", "users",
    ]:
        op.drop_table(table)
