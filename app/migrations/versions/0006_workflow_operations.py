"""Persistent reviews, checkpoints and time triggers above existing Workflows."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_definitions", sa.Column("review_policy", sa.String(), nullable=False, server_default="AUTO"))
    op.add_column("task_runs", sa.Column("execution_override", sa.Text(), nullable=True))
    op.add_column("workflow_runs", sa.Column("paused", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("workflow_runs", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table("approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_run_id", sa.String(), sa.ForeignKey("task_runs.id"), nullable=False, unique=True),
        sa.Column("policy", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("decision", sa.String()), sa.Column("decision_hash", sa.String()),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("revision_task_run_id", sa.String(), sa.ForeignKey("task_runs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("policy IN ('REVIEW_AFTER','APPROVAL_REQUIRED')", name="ck_approval_policy"),
        sa.CheckConstraint("status IN ('WAITING','APPROVED','REJECTED','REVISION_REQUESTED','CANCELLED')", name="ck_approval_status"))
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_table("artifact_reviews",
        sa.Column("artifact_id", sa.String(), sa.ForeignKey("artifacts.id"), primary_key=True),
        sa.Column("approval_id", sa.String(), sa.ForeignKey("approvals.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','REVISION_REQUESTED','CANCELLED')", name="ck_artifact_review_status"))
    op.create_index("ix_artifact_reviews_approval_id", "artifact_reviews", ["approval_id"])
    op.create_table("workflow_checkpoints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workflow_run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), nullable=False),
        sa.Column("reason", sa.String(), nullable=False), sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_workflow_checkpoints_workflow_run_id", "workflow_checkpoints", ["workflow_run_id"])
    op.create_table("workflow_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workflow_definition_id", sa.String(), sa.ForeignKey("workflow_definitions.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_seconds", sa.Integer()), sa.Column("next_fire_at", sa.DateTime(timezone=True)),
        sa.Column("context", sa.Text(), nullable=False), sa.Column("misfire_policy", sa.String(), nullable=False),
        sa.Column("grace_seconds", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('ONE_TIME','RECURRING')", name="ck_schedule_kind"),
        sa.CheckConstraint("misfire_policy IN ('SKIP','FIRE_ONCE')", name="ck_schedule_misfire"),
        sa.CheckConstraint("kind = 'ONE_TIME' OR (interval_seconds IS NOT NULL AND interval_seconds >= 60)", name="ck_schedule_interval"))
    op.create_index("ix_workflow_schedules_workflow_definition_id", "workflow_schedules", ["workflow_definition_id"])
    op.create_index("ix_workflow_schedules_next_fire_at", "workflow_schedules", ["next_fire_at"])
    op.create_table("schedule_fires",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schedule_id", sa.String(), sa.ForeignKey("workflow_schedules.id"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workflow_run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), unique=True), sa.Column("error", sa.Text()),
        sa.UniqueConstraint("schedule_id", "scheduled_for", name="uq_schedule_occurrence"),
        sa.CheckConstraint("status IN ('CLAIMED','TRIGGERED','SKIPPED','CANCELLED','FAILED')", name="ck_schedule_fire_status"))
    op.create_index("ix_schedule_fires_schedule_id", "schedule_fires", ["schedule_id"])
    op.create_index("ix_schedule_fires_status", "schedule_fires", ["status"])
    op.create_table("delayed_resumes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("checkpoint_id", sa.String(), sa.ForeignKey("workflow_checkpoints.id"), nullable=False),
        sa.Column("source_task_run_id", sa.String(), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.String(), sa.ForeignKey("workflow_runs.id"), unique=True),
        sa.Column("command_key", sa.String(), unique=True), sa.Column("command_hash", sa.String()),
        sa.Column("error", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PENDING','TRIGGERED','CANCELLED','FAILED')", name="ck_delayed_resume_status"))
    for col in ("source_task_run_id", "due_at", "status"):
        op.create_index("ix_delayed_resumes_" + col, "delayed_resumes", [col])


def downgrade():
    raise RuntimeError("Restore a backup to downgrade; approval and execution history must remain intact")
