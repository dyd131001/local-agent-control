from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30})
Session = sessionmaker(engine, expire_on_commit=False)

@event.listens_for(engine, "connect")
def sqlite_settings(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=30000")

class Base(DeclarativeBase):
    pass

def now():
    return datetime.now(timezone.utc)

def read_snapshot(db):
    # sqlite3's legacy transaction mode does not BEGIN for SELECT statements.
    connection = db.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN")

def dump(row):
    result = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    if "execution_profile" in result:
        import json
        result["execution_profile"] = json.loads(result["execution_profile"]) if result["execution_profile"] else None
    if result.get("context_config"):
        import json
        config = json.loads(result["context_config"])
        for snapshot in config.get("snapshots", []): snapshot.pop("data", None)
        config.pop("instruction", None)
        result["context_config"] = config
    return result

class ExecutionDefault(Base):
    __tablename__ = "execution_defaults"
    __table_args__ = (CheckConstraint("scope IN ('GLOBAL','CATEGORY','WORK')", name="ck_execution_default_scope"),)
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String, primary_key=True)
    profile: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Work(Base):
    __tablename__ = "works"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text, unique=True)
    workspace_kind: Mapped[str] = mapped_column(String, default="MANAGED", server_default="MANAGED")
    linked_workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_layout: Mapped[str] = mapped_column(String, default="LEGACY", server_default="LEGACY")
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    provision_state: Mapped[str] = mapped_column(String, default="PROVISIONING")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"))
    name: Mapped[str] = mapped_column(String)
    relative_path: Mapped[str] = mapped_column(Text)
    location_type: Mapped[str] = mapped_column(String, default="LEGACY", server_default="LEGACY")
    location_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage_type: Mapped[str] = mapped_column(String, default="REFERENCE", server_default="REFERENCE")
    content_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    is_context: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Request(Base):
    __tablename__ = "requests"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"))
    instruction: Mapped[str] = mapped_column(Text)
    context_ids: Mapped[str] = mapped_column(Text, default="[]")
    artifact_ids: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class RequestQueue(Base):
    __tablename__ = "request_queue"
    __table_args__ = (
        CheckConstraint("condition IN ('NOW','AT_TIME','AFTER_RUN_COMPLETED','AFTER_RUN_SUCCEEDED')", name="ck_request_queue_condition"),
        CheckConstraint("status IN ('PENDING','BLOCKED','TRIGGERED','CANCELLED')", name="ck_request_queue_status"),
        CheckConstraint("condition != 'AT_TIME' OR due_at IS NOT NULL", name="ck_request_queue_due"),
        CheckConstraint("condition NOT IN ('AFTER_RUN_COMPLETED','AFTER_RUN_SUCCEEDED') OR predecessor_run_id IS NOT NULL", name="ck_request_queue_parent"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), unique=True)
    condition: Mapped[str] = mapped_column(String)
    predecessor_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    execution_profile: Mapped[str] = mapped_column(Text)
    context_config: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), unique=True, nullable=True)
    command_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    command_hash: Mapped[str] = mapped_column(String)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("thread_id", "turn_id", name="uq_run_runtime_turn"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"))
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"))
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String, default="new")
    command_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    command_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String)
    reasoning: Mapped[str] = mapped_column(String)
    execution_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversation_threads.id"), nullable=True, index=True)
    context_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_query: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    status: Mapped[str] = mapped_column(String, default="CREATED")
    phase: Mapped[str] = mapped_column(String, default="QUEUED")
    runtime_status: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_state: Mapped[str] = mapped_column(String, default="PENDING")
    safety_block: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest: Mapped[str] = mapped_column(Text, default="{}")
    final_text: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("run_id", "relative_path", name="uq_artifact_run_path"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    name: Mapped[str] = mapped_column(String)
    candidate_path: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(Text)
    location_type: Mapped[str] = mapped_column(String, default="LEGACY", server_default="LEGACY")
    location_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    staging_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String)
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    availability: Mapped[str] = mapped_column(String, default="AVAILABLE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (CheckConstraint("run_id IS NOT NULL OR workflow_run_id IS NOT NULL", name="ck_event_owner"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), index=True, nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True, nullable=True)
    task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    type: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Instruction(Base):
    __tablename__ = "run_instructions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    turn_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    delivery: Mapped[str] = mapped_column(String, default="PENDING")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

def add_event(db, run_id, kind, payload, *, workflow_run_id=None, task_run_id=None, dedupe_key=None):
    import json
    if run_id and task_run_id is None:
        task = db.query(TaskRun).filter_by(run_id=run_id).first()
        if task:
            task_run_id, workflow_run_id = task.id, task.workflow_run_id
    if dedupe_key:
        existing = db.query(Event).filter_by(dedupe_key=dedupe_key).first()
        if existing:
            return existing
    payload = {**payload}
    if workflow_run_id:
        payload.update(workflow_run_id=workflow_run_id, task_run_id=task_run_id, run_id=run_id)
        workflow = db.get(WorkflowRun, workflow_run_id)
        payload.setdefault("execution_round", workflow.execution_round)
    if task_run_id:
        task = db.get(TaskRun, task_run_id)
        payload.setdefault("task_definition_id", task.task_definition_id)
        payload.setdefault("attempt_number", task.attempt_number)
        payload.setdefault("status", task.status)
    row = Event(run_id=run_id, workflow_run_id=workflow_run_id, task_run_id=task_run_id,
                dedupe_key=dedupe_key, type=kind, payload=json.dumps(payload, ensure_ascii=False))
    db.add(row)
    return row


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    unresolved_bindings: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    instruction: Mapped[str] = mapped_column(Text)
    runtime: Mapped[str] = mapped_column(String, default="CODEX")
    model: Mapped[str] = mapped_column(String)
    reasoning: Mapped[str] = mapped_column(String)
    execution_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_policy: Mapped[str] = mapped_column(String, default="AUTO", server_default="AUTO")
    context_rule: Mapped[str] = mapped_column(Text, default="{}")
    input_rule: Mapped[str] = mapped_column(Text, default="[]")
    output_rule: Mapped[str] = mapped_column(Text, default="[]")
    workspace_mode: Mapped[str] = mapped_column(String, default="ARTIFACT_ONLY")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (CheckConstraint("task_definition_id != depends_on_task_definition_id", name="ck_dependency_self"),)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    task_definition_id: Mapped[str] = mapped_column(ForeignKey("task_definitions.id"), primary_key=True)
    depends_on_task_definition_id: Mapped[str] = mapped_column(ForeignKey("task_definitions.id"), primary_key=True)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"))
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    definition_revision: Mapped[int] = mapped_column(Integer)
    definition_snapshot: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="CREATED")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_round: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True)
    branch_from_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    command_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    command_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("workflow_run_id", "task_definition_id", "attempt_number", name="uq_task_attempt"),
                     CheckConstraint("attempt_number >= 1", name="ck_task_attempt"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    task_definition_id: Mapped[str] = mapped_column(ForeignKey("task_definitions.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), unique=True, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    parent_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String, default="initial")
    execution_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, index=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    command_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    command_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskRunOutput(Base):
    __tablename__ = "task_run_outputs"
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), primary_key=True)
    output_key: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"))


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (CheckConstraint("policy IN ('REVIEW_AFTER','APPROVAL_REQUIRED')", name="ck_approval_policy"),
                     CheckConstraint("status IN ('WAITING','APPROVED','REJECTED','REVISION_REQUESTED','CANCELLED')", name="ck_approval_status"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), unique=True)
    policy: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="WAITING", index=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    revision_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ArtifactReview(Base):
    __tablename__ = "artifact_reviews"
    __table_args__ = (CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','REVISION_REQUESTED','CANCELLED')", name="ck_artifact_review_status"),)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING")


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    reason: Mapped[str] = mapped_column(String)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkflowSchedule(Base):
    __tablename__ = "workflow_schedules"
    __table_args__ = (CheckConstraint("kind IN ('ONE_TIME','RECURRING')", name="ck_schedule_kind"),
                     CheckConstraint("misfire_policy IN ('SKIP','FIRE_ONCE')", name="ck_schedule_misfire"),
                     CheckConstraint("kind = 'ONE_TIME' OR (interval_seconds IS NOT NULL AND interval_seconds >= 60)", name="ck_schedule_interval"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    workflow_definition_id: Mapped[str] = mapped_column(ForeignKey("workflow_definitions.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    context: Mapped[str] = mapped_column(Text, default="{}")
    misfire_policy: Mapped[str] = mapped_column(String, default="FIRE_ONCE")
    grace_seconds: Mapped[int] = mapped_column(Integer, default=300)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FlowPlan(Base):
    __tablename__ = "flow_plans"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="GENERATING", index=True)
    generation_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    research_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    artifact_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    resource_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    research_candidates_json: Mapped[str] = mapped_column(Text, default="[]")
    research_web: Mapped[bool] = mapped_column(Boolean, default=False)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    workflow_definition_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_definitions.id"), nullable=True)
    schedule_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_schedules.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ScheduleFire(Base):
    __tablename__ = "schedule_fires"
    __table_args__ = (UniqueConstraint("schedule_id", "scheduled_for", name="uq_schedule_occurrence"),
                     CheckConstraint("status IN ('CLAIMED','TRIGGERED','SKIPPED','CANCELLED','FAILED')", name="ck_schedule_fire_status"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("workflow_schedules.id"), index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="CLAIMED", index=True)
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), unique=True, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DelayedResume(Base):
    __tablename__ = "delayed_resumes"
    __table_args__ = (CheckConstraint("status IN ('PENDING','TRIGGERED','CANCELLED','FAILED')", name="ck_delayed_resume_status"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    checkpoint_id: Mapped[str] = mapped_column(ForeignKey("workflow_checkpoints.id"))
    source_task_run_id: Mapped[str] = mapped_column(ForeignKey("task_runs.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    instruction: Mapped[str] = mapped_column(Text)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), unique=True, nullable=True)
    command_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    command_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArtifactRelation(Base):
    __tablename__ = "artifact_relations"
    __table_args__ = (
        CheckConstraint("(kind = 'INPUT' AND target_task_run_id IS NOT NULL AND target_artifact_id IS NULL AND input_key IS NOT NULL AND expected_sha256 IS NOT NULL) OR (kind IN ('DERIVED_FROM','REVISION_OF') AND target_artifact_id IS NOT NULL AND target_task_run_id IS NULL AND source_artifact_id != target_artifact_id)", name="ck_relation_endpoints"),
        UniqueConstraint("kind", "source_artifact_id", "target_artifact_id", name="uq_artifact_edge"),
        Index("uq_task_input", "target_task_run_id", "input_key", unique=True, sqlite_where=text("kind = 'INPUT'")))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    target_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), index=True, nullable=True)
    target_task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_runs.id"), nullable=True)
    input_key: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ArtifactPublication(Base):
    __tablename__ = "artifact_publications"
    __table_args__ = (CheckConstraint("scope IN ('WORK','CATEGORY','GLOBAL')", name="ck_publication_scope"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), unique=True)
    scope: Mapped[str] = mapped_column(String)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="PUBLISHED")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    source_workflow_definition_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_definitions.id"), nullable=True)
    snapshot: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

def migrate():
    import sqlite3
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from pathlib import Path
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    # Runner holds the process lock. SQLite backup includes committed WAL pages.
    if DB_PATH.exists():
        with sqlite3.connect(DB_PATH) as source:
            exists = source.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
            revision = source.execute("SELECT version_num FROM alembic_version").fetchone() if exists else None
            if revision and revision[0] != ScriptDirectory.from_config(cfg).get_current_head():
                backup = DB_PATH.with_name(f"control.before-{revision[0]}-{now().strftime('%Y%m%dT%H%M%S%f')}.db")
                with sqlite3.connect(backup) as target:
                    source.backup(target)
    with engine.begin() as connection:
        # Python sqlite3's legacy mode does not BEGIN for DDL. Start a real
        # transaction so all ALTER TABLE statements and Alembic's version
        # update either commit together or roll back together.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Database foreign key validation failed after migration")

# Phase 4 adds conversation metadata without replacing Runtime or Workflow records.
class ThreadRecord(Base):
    __tablename__ = 'conversation_threads'
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','IDLE','ARCHIVED','CLOSED','EPHEMERAL','SUPERSEDED')", name='ck_conversation_status'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey('works.id'), index=True)
    codex_thread_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default='IDLE')
    parent_thread_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_threads.id'), nullable=True)
    relation_type: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[str] = mapped_column(Text, default='{}')
    compact_state: Mapped[str] = mapped_column(String, default='NONE')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Resource(Base):
    __tablename__ = 'context_resources'
    __table_args__ = (CheckConstraint("scope IN ('THREAD','WORK','CATEGORY','GLOBAL')", name='ck_resource_scope'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey('works.id'), index=True)
    category_id: Mapped[str] = mapped_column(ForeignKey('categories.id'))
    thread_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_threads.id'), nullable=True)
    kind: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String, default='WORK')
    title: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    default_include: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ContextPack(Base):
    __tablename__ = 'context_packs'
    __table_args__ = (UniqueConstraint('family_id','version', name='uq_context_pack_version'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    family_id: Mapped[str] = mapped_column(String, index=True)
    work_id: Mapped[str] = mapped_column(ForeignKey('works.id'), index=True)
    thread_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_threads.id'), nullable=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default='DRAFT')
    summary: Mapped[str] = mapped_column(Text)
    estimated_size: Mapped[int] = mapped_column(Integer)
    budget: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ContextPackItem(Base):
    __tablename__ = 'context_pack_items'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    context_pack_id: Mapped[str] = mapped_column(ForeignKey('context_packs.id'), index=True)
    source_type: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)
    source_hash: Mapped[str] = mapped_column(String)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    include_mode: Mapped[str] = mapped_column(String, default='FULL')
    snapshot: Mapped[str] = mapped_column(Text)

class Handoff(Base):
    __tablename__ = 'conversation_handoffs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_thread_id: Mapped[str] = mapped_column(ForeignKey('conversation_threads.id'))
    target_thread_id: Mapped[str] = mapped_column(ForeignKey('conversation_threads.id'))
    context_pack_id: Mapped[str | None] = mapped_column(ForeignKey('context_packs.id'), nullable=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Promotion(Base):
    __tablename__ = 'context_promotions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_thread_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_threads.id'), nullable=True)
    source_run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'))
    target_type: Mapped[str] = mapped_column(String)
    target_id: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class EphemeralQuery(Base):
    __tablename__ = 'ephemeral_queries'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_thread_id: Mapped[str | None] = mapped_column(ForeignKey('conversation_threads.id'), nullable=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey('conversation_threads.id'))
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), unique=True)
    context_pack_id: Mapped[str | None] = mapped_column(ForeignKey('context_packs.id'), nullable=True)
    status: Mapped[str] = mapped_column(String, default='PENDING')
    result_action: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
