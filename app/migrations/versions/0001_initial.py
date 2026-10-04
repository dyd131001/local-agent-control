"""Initial Phase 1 control plane schema."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute('\nCREATE TABLE categories (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tactive BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (name)\n)\n\n')
    op.execute('\nCREATE TABLE works (\n\tid VARCHAR NOT NULL, \n\tcategory_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription TEXT NOT NULL, \n\tpath TEXT NOT NULL, \n\tprovision_state VARCHAR NOT NULL, \n\tarchived BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(category_id) REFERENCES categories (id), \n\tUNIQUE (path)\n)\n\n')
    op.execute('\nCREATE TABLE requests (\n\tid VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\tinstruction TEXT NOT NULL, \n\tcontext_ids TEXT NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(work_id) REFERENCES works (id)\n)\n\n')
    op.execute('\nCREATE TABLE sources (\n\tid VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\trelative_path TEXT NOT NULL, \n\tcontent_type VARCHAR NOT NULL, \n\tsize INTEGER NOT NULL, \n\tsha256 VARCHAR NOT NULL, \n\tis_context BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(work_id) REFERENCES works (id)\n)\n\n')
    op.execute('\nCREATE TABLE runs (\n\tid VARCHAR NOT NULL, \n\trequest_id VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\tparent_run_id VARCHAR, \n\toperation VARCHAR NOT NULL, \n\tcommand_key VARCHAR, \n\tcommand_hash VARCHAR, \n\tthread_id VARCHAR, \n\tturn_id VARCHAR, \n\tmodel VARCHAR NOT NULL, \n\treasoning VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tphase VARCHAR NOT NULL, \n\truntime_status VARCHAR, \n\tartifact_state VARCHAR NOT NULL, \n\tsafety_block BOOLEAN NOT NULL, \n\terror TEXT, \n\tmanifest TEXT NOT NULL, \n\tfinal_text TEXT NOT NULL, \n\tcancel_requested BOOLEAN NOT NULL, \n\tcancel_reason VARCHAR, \n\tstarted_at DATETIME, \n\tcompleted_at DATETIME, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_run_runtime_turn UNIQUE (thread_id, turn_id), \n\tFOREIGN KEY(request_id) REFERENCES requests (id), \n\tFOREIGN KEY(work_id) REFERENCES works (id), \n\tFOREIGN KEY(parent_run_id) REFERENCES runs (id), \n\tUNIQUE (command_key)\n)\n\n')
    op.execute('\nCREATE TABLE artifacts (\n\tid VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tcandidate_path TEXT NOT NULL, \n\trelative_path TEXT NOT NULL, \n\tcontent_type VARCHAR NOT NULL, \n\tsize INTEGER NOT NULL, \n\tsha256 VARCHAR NOT NULL, \n\tpartial BOOLEAN NOT NULL, \n\tavailability VARCHAR NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_artifact_run_path UNIQUE (run_id, relative_path), \n\tFOREIGN KEY(work_id) REFERENCES works (id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id)\n)\n\n')
    op.execute('\nCREATE TABLE events (\n\tid INTEGER NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\ttype VARCHAR NOT NULL, \n\tpayload TEXT NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id)\n)\n\n')
    op.execute('CREATE INDEX ix_events_run_id ON events (run_id)')
    op.execute('\nCREATE TABLE run_instructions (\n\tid INTEGER NOT NULL, \n\trun_id VARCHAR NOT NULL, \n\tturn_id VARCHAR NOT NULL, \n\ttext TEXT NOT NULL, \n\tdelivery VARCHAR NOT NULL, \n\terror TEXT, \n\taccepted_at DATETIME, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id)\n)\n\n')

def downgrade():
    raise RuntimeError("Destructive downgrade is not supported; restore a backup instead")
