"""Complete Workflow replay/history and reverse dependency lookup indexes."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_events_workflow_cursor", "events", ["workflow_run_id", "id"])
    op.create_index("ix_workflow_runs_work_created", "workflow_runs", ["work_id", "created_at"])
    op.create_index("ix_dependencies_producer", "task_dependencies", ["depends_on_task_definition_id", "task_definition_id"])


def downgrade():
    raise RuntimeError("Destructive downgrade is not supported; restore a backup instead")
