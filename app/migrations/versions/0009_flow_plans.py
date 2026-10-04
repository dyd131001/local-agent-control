"""Persist human-reviewed AI workflow plans."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('flow_plans',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('work_id', sa.String(), sa.ForeignKey('works.id'), nullable=False),
        sa.Column('goal', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('generation_run_id', sa.String(), sa.ForeignKey('runs.id')),
        sa.Column('plan_json', sa.Text()),
        sa.Column('error', sa.Text()),
        sa.Column('workflow_definition_id', sa.String(), sa.ForeignKey('workflow_definitions.id')),
        sa.Column('schedule_id', sa.String(), sa.ForeignKey('workflow_schedules.id')),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_flow_plans_work_id', 'flow_plans', ['work_id'])
    op.create_index('ix_flow_plans_status', 'flow_plans', ['status'])


def downgrade():
    raise RuntimeError('Restore a backup to preserve flow plan history')
