"""Add external location metadata without rewriting existing paths or files."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("works", sa.Column("storage_layout", sa.String(), nullable=False, server_default="LEGACY"))
    op.add_column("works", sa.Column("workspace_path", sa.Text(), nullable=True))
    op.create_index("uq_works_workspace_path", "works", ["workspace_path"], unique=True)
    for table in ("sources", "artifacts"):
        op.add_column(table, sa.Column("location_type", sa.String(), nullable=False, server_default="LEGACY"))
        op.add_column(table, sa.Column("location_root", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("usage_type", sa.String(), nullable=False, server_default="REFERENCE"))
    op.add_column("artifacts", sa.Column("origin_path", sa.Text(), nullable=True))
    op.add_column("artifacts", sa.Column("staging_path", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Restore a backup to downgrade; existing workspace files must remain untouched")
