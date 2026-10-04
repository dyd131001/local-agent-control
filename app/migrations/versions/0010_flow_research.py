"""Keep discovery evidence and material IDs with reviewed flow plans."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite cannot add a foreign key constraint to an existing table in place.
    # The API only assigns IDs of Runs belonging to this plan's Work.
    # An older startup could commit one SQLite ALTER TABLE while Alembic still
    # reported 0009. Reconcile only columns whose existing definition matches
    # this revision; an incompatible schema must stop instead of being stamped.
    expected = [
        ('research_run_id', sa.Column('research_run_id', sa.String()), 'VARCHAR', False, None),
        ('evidence_json', sa.Column('evidence_json', sa.Text(), nullable=False, server_default='[]'), 'TEXT', True, "'[]'"),
        ('source_ids_json', sa.Column('source_ids_json', sa.Text(), nullable=False, server_default='[]'), 'TEXT', True, "'[]'"),
        ('artifact_ids_json', sa.Column('artifact_ids_json', sa.Text(), nullable=False, server_default='[]'), 'TEXT', True, "'[]'"),
        ('resource_ids_json', sa.Column('resource_ids_json', sa.Text(), nullable=False, server_default='[]'), 'TEXT', True, "'[]'"),
        ('research_candidates_json', sa.Column('research_candidates_json', sa.Text(), nullable=False, server_default='[]'), 'TEXT', True, "'[]'"),
        ('research_web', sa.Column('research_web', sa.Boolean(), nullable=False, server_default='0'), 'BOOLEAN', True, "'0'"),
    ]
    connection = op.get_bind()
    if connection.dialect.name != 'sqlite':
        raise RuntimeError('0010 recovery expects the SQLite storage backend')
    present = {row[1]: row for row in connection.exec_driver_sql('PRAGMA table_info(flow_plans)').fetchall()}
    if not present:
        raise RuntimeError('flow_plans is missing at revision 0009')
    for name, column, kind, required, default in expected:
        if name in present:
            row = present[name]
            actual_default = row[4]
            if (row[2].upper() != kind or bool(row[3]) != required or
                    actual_default != default):
                raise RuntimeError(f'Existing flow_plans.{name} does not match revision 0010')
            continue
        op.add_column('flow_plans', column)


def downgrade():
    raise RuntimeError('Restore a backup to preserve research evidence')
