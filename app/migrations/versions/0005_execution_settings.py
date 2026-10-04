"""Add defaults, Task overrides and immutable Run profiles without backfilling."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("execution_defaults",
                    sa.Column("scope", sa.String(), primary_key=True),
                    sa.Column("owner_id", sa.String(), primary_key=True),
                    sa.Column("profile", sa.Text(), nullable=False, server_default="{}"),
                    sa.CheckConstraint("scope IN ('GLOBAL','CATEGORY','WORK')", name="ck_execution_default_scope"))
    for table in ("runs", "task_definitions"):
        op.add_column(table, sa.Column("execution_profile", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Restore a backup to downgrade; historical execution profiles must remain untouched")
