"""Durable conditions above the existing Request / Run dispatcher."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('request_queue',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('work_id', sa.String(), sa.ForeignKey('works.id'), nullable=False),
        sa.Column('request_id', sa.String(), sa.ForeignKey('requests.id'), nullable=False, unique=True),
        sa.Column('condition', sa.String(), nullable=False),
        sa.Column('predecessor_run_id', sa.String(), sa.ForeignKey('runs.id'), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('execution_profile', sa.Text(), nullable=False),
        sa.Column('context_config', sa.Text(), nullable=False),
        sa.Column('run_id', sa.String(), sa.ForeignKey('runs.id'), nullable=True, unique=True),
        sa.Column('command_key', sa.String(), nullable=True, unique=True),
        sa.Column('command_hash', sa.String(), nullable=False),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("condition IN ('NOW','AT_TIME','AFTER_RUN_COMPLETED','AFTER_RUN_SUCCEEDED')", name='ck_request_queue_condition'),
        sa.CheckConstraint("status IN ('PENDING','BLOCKED','TRIGGERED','CANCELLED')", name='ck_request_queue_status'),
        sa.CheckConstraint("condition != 'AT_TIME' OR due_at IS NOT NULL", name='ck_request_queue_due'),
        sa.CheckConstraint("condition NOT IN ('AFTER_RUN_COMPLETED','AFTER_RUN_SUCCEEDED') OR predecessor_run_id IS NOT NULL", name='ck_request_queue_parent'))
    op.create_index('ix_request_queue_work_id', 'request_queue', ['work_id'])
    op.create_index('ix_request_queue_status', 'request_queue', ['status'])


def downgrade():
    raise RuntimeError('Restore a backup to preserve queued request history')
