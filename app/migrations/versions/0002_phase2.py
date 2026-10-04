"""Phase 2 Workflow schema. Frozen DDL; never imports application models."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE works ADD COLUMN workspace_kind VARCHAR NOT NULL DEFAULT 'MANAGED' CHECK (workspace_kind IN ('MANAGED','LINKED'))")
    op.execute("ALTER TABLE works ADD COLUMN linked_workspace_path TEXT CHECK ((workspace_kind = 'MANAGED' AND linked_workspace_path IS NULL) OR (workspace_kind = 'LINKED' AND linked_workspace_path IS NOT NULL))")
    op.execute("ALTER TABLE requests ADD COLUMN artifact_ids TEXT NOT NULL DEFAULT '[]'")
    op.execute('\nCREATE TABLE workflow_definitions (\n\tid VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription TEXT NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\trevision INTEGER NOT NULL, \n\tunresolved_bindings TEXT NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(work_id) REFERENCES works (id)\n)\n\n')
    op.execute('CREATE INDEX ix_workflow_definitions_work_id ON workflow_definitions (work_id)')
    op.execute('\nCREATE TABLE task_definitions (\n\tid VARCHAR NOT NULL, \n\tworkflow_definition_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tinstruction TEXT NOT NULL, \n\truntime VARCHAR NOT NULL, \n\tmodel VARCHAR NOT NULL, \n\treasoning VARCHAR NOT NULL, \n\tcontext_rule TEXT NOT NULL, \n\tinput_rule TEXT NOT NULL, \n\toutput_rule TEXT NOT NULL, \n\tworkspace_mode VARCHAR NOT NULL, \n\tdisplay_order INTEGER NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workflow_definition_id) REFERENCES workflow_definitions (id)\n)\n\n')
    op.execute('CREATE INDEX ix_task_definitions_workflow_definition_id ON task_definitions (workflow_definition_id)')
    op.execute('\nCREATE TABLE task_dependencies (\n\tworkflow_definition_id VARCHAR NOT NULL, \n\ttask_definition_id VARCHAR NOT NULL, \n\tdepends_on_task_definition_id VARCHAR NOT NULL, \n\tPRIMARY KEY (task_definition_id, depends_on_task_definition_id), \n\tCONSTRAINT ck_dependency_self CHECK (task_definition_id != depends_on_task_definition_id), \n\tFOREIGN KEY(workflow_definition_id) REFERENCES workflow_definitions (id), \n\tFOREIGN KEY(task_definition_id) REFERENCES task_definitions (id), \n\tFOREIGN KEY(depends_on_task_definition_id) REFERENCES task_definitions (id)\n)\n\n')
    op.execute('CREATE INDEX ix_task_dependencies_workflow_definition_id ON task_dependencies (workflow_definition_id)')
    op.execute('\nCREATE TABLE workflow_runs (\n\tid VARCHAR NOT NULL, \n\tworkflow_definition_id VARCHAR NOT NULL, \n\twork_id VARCHAR NOT NULL, \n\tdefinition_revision INTEGER NOT NULL, \n\tdefinition_snapshot TEXT NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\texecution_round INTEGER NOT NULL, \n\tcancel_requested BOOLEAN NOT NULL, \n\tparent_workflow_run_id VARCHAR, \n\tbranch_from_task_run_id VARCHAR, \n\tcommand_key VARCHAR, \n\tcommand_hash VARCHAR, \n\terror TEXT, \n\tcreated_at DATETIME NOT NULL, \n\tstarted_at DATETIME, \n\tcompleted_at DATETIME, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(workflow_definition_id) REFERENCES workflow_definitions (id), \n\tFOREIGN KEY(work_id) REFERENCES works (id), \n\tFOREIGN KEY(parent_workflow_run_id) REFERENCES workflow_runs (id), \n\tFOREIGN KEY(branch_from_task_run_id) REFERENCES task_runs (id), \n\tUNIQUE (command_key)\n)\n\n')
    op.execute('CREATE INDEX ix_workflow_runs_work_id ON workflow_runs (work_id)')
    op.execute('\nCREATE TABLE task_runs (\n\tid VARCHAR NOT NULL, \n\tworkflow_run_id VARCHAR NOT NULL, \n\ttask_definition_id VARCHAR NOT NULL, \n\trun_id VARCHAR, \n\tattempt_number INTEGER NOT NULL, \n\tparent_task_run_id VARCHAR, \n\toperation VARCHAR NOT NULL, \n\tstatus VARCHAR NOT NULL, \n\tblocked_reason TEXT, \n\tcancel_requested BOOLEAN NOT NULL, \n\tcommand_key VARCHAR, \n\tcommand_hash VARCHAR, \n\terror TEXT, \n\tcontract_report TEXT, \n\tcreated_at DATETIME NOT NULL, \n\tstarted_at DATETIME, \n\tcompleted_at DATETIME, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_task_attempt UNIQUE (workflow_run_id, task_definition_id, attempt_number), \n\tCONSTRAINT ck_task_attempt CHECK (attempt_number >= 1), \n\tFOREIGN KEY(workflow_run_id) REFERENCES workflow_runs (id), \n\tFOREIGN KEY(task_definition_id) REFERENCES task_definitions (id), \n\tUNIQUE (run_id), \n\tFOREIGN KEY(run_id) REFERENCES runs (id), \n\tFOREIGN KEY(parent_task_run_id) REFERENCES task_runs (id), \n\tUNIQUE (command_key)\n)\n\n')
    op.execute('CREATE INDEX ix_task_runs_status ON task_runs (status)')
    op.execute('CREATE INDEX ix_task_runs_workflow_run_id ON task_runs (workflow_run_id)')
    op.execute('\nCREATE TABLE task_run_outputs (\n\ttask_run_id VARCHAR NOT NULL, \n\toutput_key VARCHAR NOT NULL, \n\tartifact_id VARCHAR NOT NULL, \n\tPRIMARY KEY (task_run_id, output_key), \n\tFOREIGN KEY(task_run_id) REFERENCES task_runs (id), \n\tFOREIGN KEY(artifact_id) REFERENCES artifacts (id)\n)\n\n')
    op.execute("\nCREATE TABLE artifact_relations (\n\tid VARCHAR NOT NULL, \n\tkind VARCHAR NOT NULL, \n\tsource_artifact_id VARCHAR NOT NULL, \n\ttarget_artifact_id VARCHAR, \n\ttarget_task_run_id VARCHAR, \n\tinput_key VARCHAR, \n\texpected_sha256 VARCHAR, \n\tsnapshot_path TEXT, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_relation_endpoints CHECK ((kind = 'INPUT' AND target_task_run_id IS NOT NULL AND target_artifact_id IS NULL AND input_key IS NOT NULL AND expected_sha256 IS NOT NULL) OR (kind IN ('DERIVED_FROM','REVISION_OF') AND target_artifact_id IS NOT NULL AND target_task_run_id IS NULL AND source_artifact_id != target_artifact_id)), \n\tCONSTRAINT uq_artifact_edge UNIQUE (kind, source_artifact_id, target_artifact_id), \n\tFOREIGN KEY(source_artifact_id) REFERENCES artifacts (id), \n\tFOREIGN KEY(target_artifact_id) REFERENCES artifacts (id), \n\tFOREIGN KEY(target_task_run_id) REFERENCES task_runs (id)\n)\n\n")
    op.execute('CREATE INDEX ix_artifact_relations_source_artifact_id ON artifact_relations (source_artifact_id)')
    op.execute('CREATE INDEX ix_artifact_relations_target_artifact_id ON artifact_relations (target_artifact_id)')
    op.execute("CREATE UNIQUE INDEX uq_task_input ON artifact_relations (target_task_run_id, input_key) WHERE kind = 'INPUT'")
    op.execute("\nCREATE TABLE artifact_publications (\n\tid VARCHAR NOT NULL, \n\tartifact_id VARCHAR NOT NULL, \n\tscope VARCHAR NOT NULL, \n\tcategory_id VARCHAR, \n\tstatus VARCHAR NOT NULL, \n\tpublished_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_publication_scope CHECK (scope IN ('WORK','CATEGORY','GLOBAL')), \n\tUNIQUE (artifact_id), \n\tFOREIGN KEY(artifact_id) REFERENCES artifacts (id), \n\tFOREIGN KEY(category_id) REFERENCES categories (id)\n)\n\n")
    op.execute('\nCREATE TABLE workflow_templates (\n\tid VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tdescription TEXT NOT NULL, \n\tsource_workflow_definition_id VARCHAR, \n\tsnapshot TEXT NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_workflow_definition_id) REFERENCES workflow_definitions (id)\n)\n\n')
    with op.batch_alter_table("events") as batch:
        batch.alter_column("run_id", existing_type=sa.String(), nullable=True)
        batch.add_column(sa.Column("workflow_run_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("task_run_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("dedupe_key", sa.String(), nullable=True))
        batch.create_foreign_key("fk_event_workflow", "workflow_runs", ["workflow_run_id"], ["id"])
        batch.create_foreign_key("fk_event_task", "task_runs", ["task_run_id"], ["id"])
        batch.create_unique_constraint("uq_event_dedupe", ["dedupe_key"])
        batch.create_check_constraint("ck_event_owner", "run_id IS NOT NULL OR workflow_run_id IS NOT NULL")
        batch.create_check_constraint("ck_event_task_owner", "task_run_id IS NULL OR workflow_run_id IS NOT NULL")
        batch.create_index("ix_events_workflow_run_id", ["workflow_run_id"])

def downgrade():
    raise RuntimeError("Destructive downgrade is not supported; restore a backup instead")
