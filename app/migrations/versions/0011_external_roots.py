"""Persist Work external browse/read roots without changing existing plans."""
from alembic import op
import sqlalchemy as sa

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    present = {row[1]: row for row in connection.exec_driver_sql('PRAGMA table_info(works)').fetchall()}
    if 'external_roots' not in present:
        op.add_column('works', sa.Column('external_roots', sa.Text(), nullable=False, server_default='[]'))
    elif present['external_roots'][2].upper() != 'TEXT' or present['external_roots'][4] != "'[]'":
        raise RuntimeError('Existing works.external_roots does not match revision 0011')


def downgrade():
    raise RuntimeError('Restore a backup to preserve external root permissions')
