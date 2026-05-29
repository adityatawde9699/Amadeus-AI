"""add cognitive runtime tables

Revision ID: c9f31d0a7b42
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29 12:00:00.000000

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c9f31d0a7b42"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


plan_status = sa.Enum(
    "DRAFT",
    "READY",
    "RUNNING",
    "BLOCKED",
    "FAILED",
    "COMPLETED",
    "CANCELLED",
    name="cognitiveplanstatusdb",
)
step_status = sa.Enum(
    "PENDING",
    "RUNNING",
    "VERIFYING",
    "COMPLETED",
    "FAILED",
    "SKIPPED",
    name="cognitivestepstatusdb",
)


def upgrade() -> None:
    op.create_table(
        "cognitive_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.String(length=256), nullable=False),
        sa.Column("goal_id", sa.String(length=64), nullable=True),
        sa.Column("original_task", sa.Text(), nullable=False),
        sa.Column("status", plan_status, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("final_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cognitive_plans_request_id", "cognitive_plans", ["request_id"])
    op.create_index("ix_cognitive_plans_session_id", "cognitive_plans", ["session_id"])
    op.create_index("ix_cognitive_plans_user_id", "cognitive_plans", ["user_id"])
    op.create_index("ix_cognitive_plans_goal_id", "cognitive_plans", ["goal_id"])
    op.create_index("ix_cognitive_plans_status", "cognitive_plans", ["status"])
    op.create_index("ix_cognitive_plans_created_at", "cognitive_plans", ["created_at"])
    op.create_index("ix_cognitive_plans_updated_at", "cognitive_plans", ["updated_at"])
    op.create_index(
        "idx_cognitive_plan_session_status",
        "cognitive_plans",
        ["session_id", "status"],
    )
    op.create_index(
        "idx_cognitive_plan_request_status",
        "cognitive_plans",
        ["request_id", "status"],
    )

    op.create_table(
        "cognitive_plan_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=True),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["cognitive_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cognitive_plan_steps_plan_id", "cognitive_plan_steps", ["plan_id"])
    op.create_index("ix_cognitive_plan_steps_tool", "cognitive_plan_steps", ["tool"])
    op.create_index("ix_cognitive_plan_steps_status", "cognitive_plan_steps", ["status"])
    op.create_index("ix_cognitive_plan_steps_risk_level", "cognitive_plan_steps", ["risk_level"])
    op.create_index("ix_cognitive_plan_steps_started_at", "cognitive_plan_steps", ["started_at"])
    op.create_index("ix_cognitive_plan_steps_completed_at", "cognitive_plan_steps", ["completed_at"])
    op.create_index("ix_cognitive_plan_steps_created_at", "cognitive_plan_steps", ["created_at"])
    op.create_index(
        "idx_cognitive_step_plan_status",
        "cognitive_plan_steps",
        ["plan_id", "status"],
    )
    op.create_index(
        "idx_cognitive_step_tool_status",
        "cognitive_plan_steps",
        ["tool", "status"],
    )

    op.create_table(
        "cognitive_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("observation_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["cognitive_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["cognitive_plan_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cognitive_observations_plan_id", "cognitive_observations", ["plan_id"])
    op.create_index("ix_cognitive_observations_step_id", "cognitive_observations", ["step_id"])
    op.create_index("ix_cognitive_observations_source", "cognitive_observations", ["source"])
    op.create_index("ix_cognitive_observations_success", "cognitive_observations", ["success"])
    op.create_index("ix_cognitive_observations_created_at", "cognitive_observations", ["created_at"])
    op.create_index(
        "idx_cognitive_observation_plan_created",
        "cognitive_observations",
        ["plan_id", "created_at"],
    )
    op.create_index(
        "idx_cognitive_observation_step_created",
        "cognitive_observations",
        ["step_id", "created_at"],
    )

    op.create_table(
        "cognitive_reflections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("suggested_action", sa.String(length=128), nullable=True),
        sa.Column("is_dead_end", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["cognitive_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["step_id"], ["cognitive_plan_steps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cognitive_reflections_plan_id", "cognitive_reflections", ["plan_id"])
    op.create_index("ix_cognitive_reflections_step_id", "cognitive_reflections", ["step_id"])
    op.create_index("ix_cognitive_reflections_is_dead_end", "cognitive_reflections", ["is_dead_end"])
    op.create_index("ix_cognitive_reflections_created_at", "cognitive_reflections", ["created_at"])
    op.create_index(
        "idx_cognitive_reflection_plan_created",
        "cognitive_reflections",
        ["plan_id", "created_at"],
    )
    op.create_index(
        "idx_cognitive_reflection_dead_end",
        "cognitive_reflections",
        ["is_dead_end", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_cognitive_reflection_dead_end", table_name="cognitive_reflections")
    op.drop_index("idx_cognitive_reflection_plan_created", table_name="cognitive_reflections")
    op.drop_index("ix_cognitive_reflections_created_at", table_name="cognitive_reflections")
    op.drop_index("ix_cognitive_reflections_is_dead_end", table_name="cognitive_reflections")
    op.drop_index("ix_cognitive_reflections_step_id", table_name="cognitive_reflections")
    op.drop_index("ix_cognitive_reflections_plan_id", table_name="cognitive_reflections")
    op.drop_table("cognitive_reflections")

    op.drop_index("idx_cognitive_observation_step_created", table_name="cognitive_observations")
    op.drop_index("idx_cognitive_observation_plan_created", table_name="cognitive_observations")
    op.drop_index("ix_cognitive_observations_created_at", table_name="cognitive_observations")
    op.drop_index("ix_cognitive_observations_success", table_name="cognitive_observations")
    op.drop_index("ix_cognitive_observations_source", table_name="cognitive_observations")
    op.drop_index("ix_cognitive_observations_step_id", table_name="cognitive_observations")
    op.drop_index("ix_cognitive_observations_plan_id", table_name="cognitive_observations")
    op.drop_table("cognitive_observations")

    op.drop_index("idx_cognitive_step_tool_status", table_name="cognitive_plan_steps")
    op.drop_index("idx_cognitive_step_plan_status", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_created_at", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_completed_at", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_started_at", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_risk_level", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_status", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_tool", table_name="cognitive_plan_steps")
    op.drop_index("ix_cognitive_plan_steps_plan_id", table_name="cognitive_plan_steps")
    op.drop_table("cognitive_plan_steps")

    op.drop_index("idx_cognitive_plan_request_status", table_name="cognitive_plans")
    op.drop_index("idx_cognitive_plan_session_status", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_updated_at", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_created_at", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_status", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_goal_id", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_user_id", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_session_id", table_name="cognitive_plans")
    op.drop_index("ix_cognitive_plans_request_id", table_name="cognitive_plans")
    op.drop_table("cognitive_plans")

    step_status.drop(op.get_bind(), checkfirst=True)
    plan_status.drop(op.get_bind(), checkfirst=True)
