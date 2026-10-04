"""Workflow definitions, frozen execution snapshots, manual Retry and Branch."""
import copy
import json
import re
import threading
from pathlib import PurePosixPath
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .db import (Artifact, ArtifactRelation, Request, Run, Source, TaskDefinition, TaskDependency, TaskRun,
                 TaskRunOutput, WorkflowDefinition, WorkflowRun, Work, add_event, dump, now)
from .workspace import ident, sha
from .artifact_service import admit_artifact, input_relation
from .execution_settings import ExecutionProfile, override

COMMAND_LOCK = threading.RLock()
ACTIVE = {"BLOCKED", "READY", "QUEUED", "RUNNING"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SKIPPED"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def row(db, cls, key):
    result = db.get(cls, key)
    if not result:
        raise HTTPException(404, f"{cls.__name__} not found")
    return result


def relative_path(path):
    if not path or path.startswith("/") or "\\" in path or any(c in path for c in "*?[]\x00"):
        raise ValueError("Output must be an exact relative path")
    if any(p in {"", ".", "..", ".git"} for p in path.split("/")) or path.split("/")[0] == "system":
        raise ValueError("Invalid or reserved output path")
    return path


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExternalScope(StrictBody):
    root: str = Field(min_length=2, max_length=1000)
    read_paths: list[str] = Field(default_factory=list, max_length=100)
    search_paths: list[str] = Field(default_factory=lambda: ['.'], max_length=100)

    @model_validator(mode="after")
    def paths(self):
        from pathlib import Path
        from .path_inputs import validate_selection
        if not self.root.startswith('/') or '..' in Path(self.root).parts:
            raise ValueError('External folder must be absolute without parent traversal')
        for path in self.read_paths + self.search_paths:
            validate_selection(path)
        if len(self.read_paths) != len(set(self.read_paths)) or len(self.search_paths) != len(set(self.search_paths)):
            raise ValueError('Duplicate external folder selection')
        return self


class ContextRule(StrictBody):
    inherit_workflow_context: bool = True
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    path_patterns: list[str] = Field(default_factory=list, max_length=100)
    read_paths: list[str] = Field(default_factory=list, max_length=100)
    search_paths: list[str] = Field(default_factory=list, max_length=100)
    external_scopes: list[ExternalScope] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def paths(self):
        from .path_inputs import validate_pattern, validate_selection
        for pattern in self.path_patterns:
            validate_pattern(pattern)
        if len(self.path_patterns) != len(set(self.path_patterns)):
            raise ValueError("Duplicate project path pattern")
        for path in self.read_paths + self.search_paths:
            validate_selection(path)
        if len(self.read_paths) != len(set(self.read_paths)) or len(self.search_paths) != len(set(self.search_paths)):
            raise ValueError("Duplicate project scope selection")
        if self.path_patterns and self.read_paths:
            raise ValueError("Choose project folders or legacy path patterns, not both")
        if self.search_paths and not (self.read_paths or self.path_patterns):
            raise ValueError("Choose a read scope before a search scope")
        if len({scope.root for scope in self.external_scopes}) != len(self.external_scopes):
            raise ValueError('Duplicate external folder root')
        return self


class InputRule(StrictBody):
    input_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    artifact_id: str | None = None
    task_definition_id: str | None = None
    output_key: str | None = None

    @model_validator(mode="after")
    def binding(self):
        if bool(self.artifact_id) == bool(self.task_definition_id and self.output_key) or (self.artifact_id and (self.task_definition_id or self.output_key)):
            raise ValueError("Choose an Artifact or a Task output slot")
        return self


class OutputRule(StrictBody):
    output_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    path: str = Field(max_length=500)
    required: bool = True
    media_type: str | None = None

    @model_validator(mode="after")
    def path_check(self):
        relative_path(self.path)
        if self.output_key.startswith("git_"):
            raise ValueError("git_ output slots are reserved")
        return self


class TaskBody(StrictBody):
    id: str = Field(default_factory=lambda: ident("task"), pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=30000)
    runtime: Literal["CODEX"] = "CODEX"
    model: str | None = None
    reasoning: str | None = None
    execution_profile: ExecutionProfile | None = None
    review_policy: Literal["AUTO", "REVIEW_AFTER", "APPROVAL_REQUIRED"] = "AUTO"
    context_rule: ContextRule = Field(default_factory=ContextRule)
    input_rule: list[InputRule] = Field(default_factory=list, max_length=100)
    output_rule: list[OutputRule] = Field(default_factory=list, max_length=100)
    workspace_mode: Literal["ARTIFACT_ONLY", "GIT_WORKTREE"] = "ARTIFACT_ONLY"
    display_order: int = 0
    depends_on: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_rules(self):
        if not self.name.strip() or not self.instruction.strip():
            raise ValueError("Task name and instruction cannot be blank")
        for values in ([r.input_key for r in self.input_rule], [r.output_key for r in self.output_rule], [r.path for r in self.output_rule], self.depends_on):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate input/output/dependency")
        return self


class WorkflowBody(StrictBody):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=10000)
    enabled: bool = True
    expected_revision: int | None = None
    tasks: list[TaskBody] = Field(min_length=1, max_length=100)
    unresolved_bindings: list[dict] = Field(default_factory=list, max_length=100)


def git_outputs():
    return [{"output_key": key, "path": f"system/git/{path}", "required": True, "system": True}
            for key, path in [("git_patch", "changes.patch"), ("git_changes", "changes.json"), ("git_new_files", "new-files.zip")]]


def outputs(task):
    return task["output_rule"] + (git_outputs() if task["workspace_mode"] == "GIT_WORKTREE" else [])


def validate_graph(tasks):
    by_id = {t["id"]: t for t in tasks}
    if len(by_id) != len(tasks) or not tasks:
        raise ValueError("Task IDs must be unique; workflow cannot be empty")
    remaining, order, ancestors = set(by_id), [], {}
    for t in tasks:
        if t["id"] in t["depends_on"] or not set(t["depends_on"]).issubset(by_id):
            raise ValueError(f"Invalid dependency for {t['name']}")
    while remaining:
        ready = sorted((key for key in remaining if set(by_id[key]["depends_on"]).issubset(order)),
                       key=lambda key: (by_id[key]["display_order"], key))
        if not ready:
            raise ValueError("Dependency cycle: " + ", ".join(sorted(remaining)))
        for key in ready:
            parents = by_id[key]["depends_on"]
            ancestors[key] = set(parents).union(*(ancestors[p] for p in parents))
            for binding in by_id[key]["input_rule"]:
                if binding.get("task_definition_id"):
                    producer = binding["task_definition_id"]
                    if producer not in ancestors[key]:
                        raise ValueError("Input producer must be a preceding Task")
                    slot = next((o for o in outputs(by_id[producer]) if o["output_key"] == binding["output_key"]), None)
                    if not slot or not slot["required"]:
                        raise ValueError("Input must reference a declared required output")
            order.append(key)
            remaining.remove(key)
    return order


def definition(db, definition_id):
    wf = row(db, WorkflowDefinition, definition_id)
    tasks = []
    for t in db.query(TaskDefinition).filter_by(workflow_definition_id=wf.id, enabled=True).order_by(TaskDefinition.display_order, TaskDefinition.id):
        item = {k: getattr(t, k) for k in ("id", "name", "instruction", "runtime", "model", "reasoning", "review_policy", "workspace_mode", "display_order")}
        item.update({k: json.loads(getattr(t, k)) for k in ("context_rule", "input_rule", "output_rule")})
        profile = json.loads(t.execution_profile) if t.execution_profile is not None else {"model": t.model, "reasoning": t.reasoning}
        item["execution_profile"] = profile
        item["model"], item["reasoning"] = profile.get("model"), profile.get("reasoning")
        item["depends_on"] = [d.depends_on_task_definition_id for d in db.query(TaskDependency).filter_by(task_definition_id=t.id)]
        tasks.append(item)
    return {**dump(wf), "tasks": tasks, "unresolved_bindings": json.loads(wf.unresolved_bindings)}


def validate_context(db, work, tasks, source_ids=(), artifact_ids=()):
    for t in tasks:
        if t["workspace_mode"] == "GIT_WORKTREE" and not work.linked_workspace_path:
            raise ValueError("Git worktree requires a linked Git project")
        cr = t["context_rule"]
        if any(cr.get(key) for key in ("path_patterns", "read_paths", "search_paths")) and not work.linked_workspace_path:
            raise ValueError("Project path inputs require a linked Work project")
        if any(cr.get(key) for key in ("path_patterns", "read_paths", "search_paths")):
            from pathlib import Path
            from .path_inputs import scope_preview
            selected = scope_preview(Path(work.linked_workspace_path), cr.get("read_paths", []),
                                     cr.get("search_paths", []), cr.get("path_patterns", []))
            if not selected["read_files"] or not selected["search_files"]:
                raise ValueError("Project read or search scope matches no regular files")
        for external in cr.get('external_scopes', []):
            from .path_inputs import scope_preview
            from .root_scopes import registered
            external_root, permission = registered(work, external['root'], 'read' if external['read_paths'] else 'browse')
            if external['search_paths'] and not permission.get('browse'):
                raise ValueError('Work에 탐색 권한이 없는 외부 Root입니다.')
            if external['read_paths'] and not permission.get('read'):
                raise ValueError('Work에 AI 읽기 권한이 없는 외부 Root입니다.')
            selected = scope_preview(external_root, external['read_paths'] or ['.'], external['search_paths'],
                                     custom=permission.get('ignore_patterns', []))
            if (external['search_paths'] and not selected['search_files']) or (external['read_paths'] and not selected['read_files']):
                raise ValueError('External search scope matches no regular files')
        ids = list(cr.get("source_ids", [])) + list(source_ids)
        if len(ids) != len(set(ids)) and len(set(cr.get("source_ids", []))) != len(cr.get("source_ids", [])):
            raise ValueError("Duplicate source IDs")
        for sid in set(ids):
            s = db.get(Source, sid)
            if not s or s.work_id != work.id:
                raise ValueError("Invalid Source selection")
        aids = cr.get("artifact_ids", []) + list(artifact_ids) + [i["artifact_id"] for i in t["input_rule"] if i.get("artifact_id")]
        for aid in set(aids):
            admit_artifact(db, aid, work)


def save_definition(db, work, body, existing=None):
    tasks = [t.model_dump() for t in body.tasks]
    validate_graph(tasks)
    validate_context(db, work, tasks)
    if body.enabled and body.unresolved_bindings:
        raise HTTPException(409, "Resolve or explicitly exclude Template bindings first")
    if existing:
        changed = db.query(WorkflowDefinition).filter_by(id=existing.id, revision=body.expected_revision).update(
            {WorkflowDefinition.revision: WorkflowDefinition.revision + 1}, synchronize_session=False)
        if not changed:
            raise HTTPException(409, "Workflow changed; reload before saving")
        db.refresh(existing)
        wf = existing
        db.query(TaskDependency).filter_by(workflow_definition_id=wf.id).delete()
        for old in db.query(TaskDefinition).filter_by(workflow_definition_id=wf.id):
            old.enabled = False
    else:
        wf = WorkflowDefinition(id=ident("wf"), work_id=work.id, name=body.name,
                                description=body.description, enabled=body.enabled,
                                unresolved_bindings=encode(body.unresolved_bindings))
        db.add(wf)
        db.flush()
    wf.name, wf.description, wf.enabled, wf.updated_at = body.name, body.description, body.enabled, now()
    wf.unresolved_bindings = encode(body.unresolved_bindings)
    for item in tasks:
        t = db.get(TaskDefinition, item["id"])
        if t and t.workflow_definition_id != wf.id:
            raise ValueError("Task ID belongs to another Workflow")
        if not t:
            t = TaskDefinition(id=item["id"], workflow_definition_id=wf.id)
            db.add(t)
        profile = override(item)
        t.execution_profile = encode(profile)
        t.model, t.reasoning = profile.get("model") or "", profile.get("reasoning") or ""
        for key in ("name", "instruction", "runtime", "review_policy", "workspace_mode", "display_order"):
            setattr(t, key, item[key])
        for key in ("context_rule", "input_rule", "output_rule"):
            setattr(t, key, encode(item[key]))
        t.enabled, t.updated_at = True, now()
    db.flush()
    for item in tasks:
        for parent in item["depends_on"]:
            db.add(TaskDependency(workflow_definition_id=wf.id, task_definition_id=item["id"], depends_on_task_definition_id=parent))
    db.flush()
    return wf


def command(db, cls, scope, key, body):
    digest = sha(encode(body).encode())
    if not key:
        return None, None, digest
    if len(key) > 160:
        raise HTTPException(400, "Idempotency key too long")
    key = f"{scope}:{key}"
    existing = db.query(cls).filter_by(command_key=key).first()
    if existing and existing.command_hash != digest:
        raise HTTPException(409, "Idempotency key used with different input")
    return existing, key, digest


def safe_to_start(db, work):
    if work.archived or work.provision_state != "READY":
        raise HTTPException(409, "Work is archived or not ready")
    from .db import Category
    if not db.get(Category,work.category_id).active:
        raise HTTPException(409,"비활성 Category에서는 실행할 수 없습니다. 관리 화면에서 다시 활성화하세요.")
    if db.query(Run).filter_by(safety_block=True).first():
        raise HTTPException(409, "Reconcile the unknown Runtime outcome first")


def task_event(db, task, kind, payload=None, *, suffix=""):
    wr = db.get(WorkflowRun, task.workflow_run_id)
    return add_event(db, task.run_id, kind,
                     {"task_definition_id": task.task_definition_id, "attempt_number": task.attempt_number,
                      "status": task.status, "execution_round": wr.execution_round, **(payload or {})}, workflow_run_id=task.workflow_run_id,
                     task_run_id=task.id, dedupe_key=f"{task.id}:{kind}:{suffix}")


def new_execution(db, wf, snapshot, key=None, digest=None, parent=None, branch_task=None):
    wr = WorkflowRun(id=ident("wfr"), workflow_definition_id=wf.id, work_id=wf.work_id,
                     definition_revision=parent.definition_revision if parent else wf.revision, definition_snapshot=encode(snapshot), command_key=key,
                     command_hash=digest, parent_workflow_run_id=parent.id if parent else None,
                     branch_from_task_run_id=branch_task.id if branch_task else None)
    db.add(wr)
    db.flush()
    for t in snapshot["tasks"]:
        status = "BLOCKED" if t["depends_on"] else "READY"
        tr = TaskRun(id=ident("tr"), workflow_run_id=wr.id, task_definition_id=t["id"], status=status,
                     operation="branch" if branch_task else "initial", parent_task_run_id=branch_task.id if branch_task else None,
                     blocked_reason=encode({"code": "DEPENDENCY_PENDING", "task_ids": t["depends_on"]}) if t["depends_on"] else None)
        db.add(tr)
        db.flush()
        task_event(db, tr, f"TASK_{status}")
    add_event(db, None, "WORKFLOW_CREATED", {"status": "CREATED"}, workflow_run_id=wr.id, dedupe_key=f"{wr.id}:created")
    return wr


def latest_attempts(db, wr_id):
    current = {}
    for t in db.query(TaskRun).filter_by(workflow_run_id=wr_id).order_by(TaskRun.attempt_number):
        current[t.task_definition_id] = t
    return current


def reopen(db, wr):
    if wr.status in {"PARTIAL", "FAILED"}:
        old = {"status": wr.status, "error": wr.error}
        wr.execution_round += 1
        wr.completed_at, wr.error = None, None
        wr.status = "RUNNING"
        add_event(db, None, "WORKFLOW_STARTED", {"execution_round": wr.execution_round, "previous": old},
                  workflow_run_id=wr.id, dedupe_key=f"{wr.id}:started:{wr.execution_round}")


def retry_task(db, source, key):
    existing, ckey, digest = command(db, TaskRun, f"retry:{source.id}", key, {})
    if existing:
        return existing
    wr = row(db, WorkflowRun, source.workflow_run_id)
    safe_to_start(db, row(db, Work, wr.work_id))
    current = latest_attempts(db, wr.id)
    if source.status != "FAILED" or current[source.task_definition_id].id != source.id or wr.status in {"COMPLETED", "CANCELLED"} or wr.cancel_requested:
        raise HTTPException(409, "Retry requires the current confirmed failed attempt")
    descendants = {source.task_definition_id}
    specs = {t["id"]: t for t in json.loads(wr.definition_snapshot)["tasks"]}
    for key_id in validate_graph(list(specs.values())):
        if set(specs[key_id]["depends_on"]) & descendants:
            descendants.add(key_id)
    if any(current[x].status != "BLOCKED" for x in descendants - {source.task_definition_id}):
        raise HTTPException(409, "Descendants have already started or were abandoned; create a new execution")
    tr = TaskRun(id=ident("tr"), workflow_run_id=wr.id, task_definition_id=source.task_definition_id,
                 attempt_number=source.attempt_number + 1, parent_task_run_id=source.id, operation="retry",
                 status="READY", command_key=ckey, command_hash=digest, execution_override=source.execution_override)
    db.add(tr)
    db.flush()
    for relation in db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=source.id):
        a = db.get(Artifact, relation.source_artifact_id)
        r = input_relation(db, tr, relation.input_key, a)
        r.expected_sha256 = relation.expected_sha256
    reopen(db, wr)
    task_event(db, tr, "RETRY_CREATED", {"parent_task_run_id": source.id})
    task_event(db, tr, "TASK_READY")
    return tr
