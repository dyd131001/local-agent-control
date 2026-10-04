"""Phase 2 APIs using the existing session guard, Runner and Event store."""
import asyncio
import copy
import json
from typing import Literal
from fastapi import APIRouter, HTTPException, Request as HttpRequest
from fastapi.responses import StreamingResponse
from pydantic import Field
from .db import (Approval, Artifact, ArtifactRelation, ArtifactReview, Event, Run, Session, Source, TaskDefinition, TaskRun, TaskRunOutput,
                 Work, WorkflowDefinition, WorkflowRun, WorkflowTemplate, add_event, dump, now, read_snapshot)
from .workflow import (COMMAND_LOCK, StrictBody, WorkflowBody, TaskBody, OutputRule, command, definition, encode,
                       latest_attempts, new_execution, outputs, retry_task, row, safe_to_start, save_definition,
                       task_event, validate_context, validate_graph)
from .artifact_service import admit_artifact, library, publish
from .scheduler import aggregate, cancel_task
from .workspace import ident, register_source, safe_read
from .git_workspace import baseline
from .storage import register_reference, workspace_root, remove_published_staging
from .execution_settings import ExecutionProfile, catalog_from, inherited, override, resolve, legacy_profile
from .workflow_operations import worker_profile

router = APIRouter(prefix="/api")
runner = None


def configure(shared_runner):
    global runner
    runner = shared_runner
    return router


class StartBody(StrictBody):
    expected_revision: int | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)


class BranchBody(StrictBody):
    instruction: str = Field(min_length=1, max_length=30000)
    model: str | None = None
    reasoning: str | None = None
    execution_profile: ExecutionProfile | None = None
    source_output_keys: list[str] | None = None
    output_rule: list[OutputRule] | None = None
    history_mode: Literal["ARTIFACT", "FORK"] = "ARTIFACT"
    revision_of: dict[str, str] = Field(default_factory=dict)


class PublishBody(StrictBody):
    scope: Literal["WORK", "CATEGORY", "GLOBAL"]


class CloneBody(StrictBody):
    target_work_id: str


class TemplateBody(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str = Field(default="", max_length=10000)


class ImportBody(StrictBody):
    paths: list[str] = Field(min_length=1, max_length=100)


async def check_models(tasks, work_id=None):
    catalog = await catalog_from(runner.gateway)
    with Session() as db:
        work = row(db, Work, work_id) if work_id else None
        parent = inherited(db, work)
        for task in tasks:
            worker_profile(resolve(catalog, parent, override(task)))
    return catalog


def detail(db, wr):
    read_snapshot(db)
    db.refresh(wr)
    current = latest_attempts(db, wr.id)
    attempts = db.query(TaskRun).filter_by(workflow_run_id=wr.id).order_by(TaskRun.created_at, TaskRun.attempt_number).all()
    result = []
    for t in attempts:
        inputs = [{**dump(r), "artifact": dump(db.get(Artifact, r.source_artifact_id))}
                  for r in db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=t.id)]
        out = [{"output_key": o.output_key, "artifact": dump(db.get(Artifact, o.artifact_id))}
               for o in db.query(TaskRunOutput).filter_by(task_run_id=t.id)]
        result.append({**dump(t), "is_current": current[t.task_definition_id].id == t.id,
                       "approval":dump(a) if (a := db.query(Approval).filter_by(task_run_id=t.id).first()) else None,
                       "inputs": inputs, "outputs": out, "run": dump(db.get(Run, t.run_id)) if t.run_id else None})
    events = db.query(Event).filter_by(workflow_run_id=wr.id).order_by(Event.id).all()
    return {"workflow_run": dump(wr), "snapshot": json.loads(wr.definition_snapshot), "task_runs": result,
            "events": [{**dump(e), "payload": json.loads(e.payload)} for e in events],
            "last_event_id": events[-1].id if events else 0,
            "branches": [dump(w) for w in db.query(WorkflowRun).filter_by(parent_workflow_run_id=wr.id)],
            "max_parallel_tasks": runner.max_parallel_tasks}


@router.get("/works/{work_id}/workflows")
def list_workflows(work_id: str):
    with Session() as db:
        row(db, Work, work_id)
        return [dump(w) for w in db.query(WorkflowDefinition).filter_by(work_id=work_id).order_by(WorkflowDefinition.created_at)]


@router.post("/works/{work_id}/workflows", status_code=201)
async def create_workflow(work_id: str, body: WorkflowBody):
    await check_models([t.model_dump() for t in body.tasks], work_id)
    if any(t.workspace_mode == "GIT_WORKTREE" for t in body.tasks):
        with Session() as db:
            work = row(db, Work, work_id)
        await asyncio.to_thread(baseline, work)
    with COMMAND_LOCK, Session() as db:
        wf = save_definition(db, row(db, Work, work_id), body)
        db.commit()
        return definition(db, wf.id)


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str):
    with Session() as db:
        return definition(db, workflow_id)


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowBody):
    with Session() as db:
        work_id = row(db, WorkflowDefinition, workflow_id).work_id
    await check_models([t.model_dump() for t in body.tasks], work_id)
    if any(t.workspace_mode == "GIT_WORKTREE" for t in body.tasks):
        with Session() as db:
            work = row(db, Work, row(db, WorkflowDefinition, workflow_id).work_id)
        await asyncio.to_thread(baseline, work)
    with COMMAND_LOCK, Session() as db:
        wf = row(db, WorkflowDefinition, workflow_id)
        save_definition(db, row(db, Work, wf.work_id), body, wf)
        db.commit()
        return definition(db, wf.id)


@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str):
    with COMMAND_LOCK, Session() as db:
        wf = row(db, WorkflowDefinition, workflow_id)
        wf.enabled, wf.revision, wf.updated_at = False, wf.revision + 1, now()
        db.commit()
        return dump(wf)


@router.get("/workflows/{workflow_id}/tasks")
def list_tasks(workflow_id: str):
    return get_workflow(workflow_id)["tasks"]


async def edit_task(workflow_id, expected_revision, task=None, task_id=None, delete=False):
    data = get_workflow(workflow_id)
    tasks = data["tasks"]
    if task_id:
        if not any(t["id"] == task_id for t in tasks):
            raise HTTPException(404, "Task not found")
        tasks = [t for t in tasks if t["id"] != task_id]
    if not delete:
        item = task.model_dump()
        if task_id:
            item["id"] = task_id
        tasks.append(item)
    body = WorkflowBody(name=data["name"], description=data["description"], enabled=data["enabled"],
                        expected_revision=expected_revision, tasks=tasks, unresolved_bindings=data["unresolved_bindings"])
    return await update_workflow(workflow_id, body)


@router.post("/workflows/{workflow_id}/tasks", status_code=201)
async def add_task(workflow_id: str, expected_revision: int, body: TaskBody):
    return await edit_task(workflow_id, expected_revision, task=body)


@router.put("/workflows/{workflow_id}/tasks/{task_id}")
async def update_task(workflow_id: str, task_id: str, expected_revision: int, body: TaskBody):
    return await edit_task(workflow_id, expected_revision, task=body, task_id=task_id)


@router.delete("/workflows/{workflow_id}/tasks/{task_id}")
async def delete_task(workflow_id: str, task_id: str, expected_revision: int):
    return await edit_task(workflow_id, expected_revision, task_id=task_id, delete=True)


@router.post("/workflows/{workflow_id}/runs", status_code=202)
async def start_execution(workflow_id: str, body: StartBody, http: HttpRequest):
    return await start_managed_execution(workflow_id, body, http)


async def start_managed_execution(workflow_id, body, http, *, schedule_fire_id=None):
    key = http.headers.get("idempotency-key")
    with Session() as db:
        existing, ckey, digest = command(db, WorkflowRun, f"start:{workflow_id}", key, body.model_dump())
        if existing:
            return detail(db, existing)
        data = definition(db, workflow_id)
        work = row(db, Work, data["work_id"])
        revision = data["revision"]
        from .path_inputs import READ_SCOPE_ENFORCED
        if not READ_SCOPE_ENFORCED and any(any(t["context_rule"].get(key) for key in ("path_patterns", "read_paths", "search_paths", "external_scopes")) for t in data["tasks"]):
            raise HTTPException(409, "PROJECT_PATH_SCOPE_UNENFORCED: 현재 런타임은 선택한 프로젝트 경로 밖의 읽기를 차단할 수 없어 실행을 시작하지 않습니다.")
    catalog = await catalog_from(runner.gateway)
    git_commit = await asyncio.to_thread(baseline, work) if any(t["workspace_mode"] == "GIT_WORKTREE" for t in data["tasks"]) else None
    with COMMAND_LOCK, Session() as db:
        if schedule_fire_id:
            from .db import ScheduleFire, WorkflowSchedule
            from .workflow_operations import transaction
            transaction(db)
            fire = row(db, ScheduleFire, schedule_fire_id)
            schedule = row(db, WorkflowSchedule, fire.schedule_id)
            if fire.status != "CLAIMED" or not schedule.enabled or schedule.workflow_definition_id != workflow_id:
                raise HTTPException(409, "Schedule occurrence was cancelled or already triggered")
        existing, ckey, digest = command(db, WorkflowRun, f"start:{workflow_id}", key, body.model_dump())
        if existing:
            return detail(db, existing)
        wf = row(db, WorkflowDefinition, workflow_id)
        safe_to_start(db, row(db, Work, wf.work_id))
        if not wf.enabled or json.loads(wf.unresolved_bindings):
            raise HTTPException(409, "Workflow disabled or Template bindings unresolved")
        if wf.revision != revision or (body.expected_revision is not None and wf.revision != body.expected_revision):
            raise HTTPException(409, "Workflow revision changed")
        validate_graph(data["tasks"])
        validate_context(db, work, data["tasks"], body.source_ids, body.artifact_ids)
        parent_profile = inherited(db, row(db, Work, wf.work_id))
        for task in data["tasks"]:
            profile = resolve(catalog, parent_profile, override(task))
            worker_profile(profile)
            task["execution_profile"] = profile
            task["model"], task["reasoning"] = profile["model"], profile["reasoning"]
        source_ids = set(body.source_ids)
        artifact_ids = set(body.artifact_ids)
        for task in data["tasks"]:
            source_ids.update(task["context_rule"]["source_ids"])
            artifact_ids.update(task["context_rule"]["artifact_ids"])
            artifact_ids.update(b["artifact_id"] for b in task["input_rule"] if b.get("artifact_id"))
        from .root_scopes import roots
        snapshot = {"schema_version": 1, "tasks": data["tasks"], "workflow_context": body.model_dump(exclude={"expected_revision"}),
                    "external_root_capabilities": roots(work),
                    "source_hashes": {sid: db.get(Source, sid).sha256 for sid in source_ids},
                    "artifact_hashes": {aid: db.get(Artifact, aid).sha256 for aid in artifact_ids}, "git_base_commit": git_commit,
                    "workspace_path": str(workspace_root(work))}
        wr = new_execution(db, wf, snapshot, ckey, digest)
        if schedule_fire_id:
            fire.status, fire.workflow_run_id, fire.error = "TRIGGERED", wr.id, None
            if schedule.kind == "ONE_TIME":
                schedule.enabled = False
            add_event(db, None, "SCHEDULE_TRIGGERED", {"schedule_id":schedule.id, "schedule_fire_id":fire.id}, workflow_run_id=wr.id)
        db.commit()
        runner.wake.set()
        return detail(db, wr)


@router.get("/works/{work_id}/workflow-runs")
def list_executions(work_id: str, offset: int = 0, limit: int = 50):
    with Session() as db:
        row(db, Work, work_id)
        return [dump(w) for w in db.query(WorkflowRun).filter_by(work_id=work_id).order_by(WorkflowRun.created_at.desc()).offset(max(0, offset)).limit(min(max(limit, 1), 100))]


@router.get("/workflow-runs/{workflow_run_id}")
def get_execution(workflow_run_id: str):
    with COMMAND_LOCK, Session() as db:
        return detail(db, row(db, WorkflowRun, workflow_run_id))


async def interrupt_many(ids):
    async def interrupt(rid):
        try:
            await asyncio.wait_for(runner.gateway.interrupt(rid), 10)
        except Exception as exc:
            runner.emit(rid, "WARNING", {"message": "Interrupt unconfirmed"})
    await asyncio.gather(*(interrupt(rid) for rid in ids))
    runner.wake.set()


@router.post("/workflow-runs/{workflow_run_id}/cancel", status_code=202)
async def cancel_workflow(workflow_run_id: str):
    with COMMAND_LOCK, Session() as db:
        wr = row(db, WorkflowRun, workflow_run_id)
        if wr.status == "COMPLETED":
            raise HTTPException(409, "Completed Workflow history cannot be cancelled")
        if wr.status == "CANCELLED":
            return detail(db, wr)
        wr.cancel_requested = True
        wr.paused = False
        for approval in db.query(Approval).join(TaskRun, Approval.task_run_id == TaskRun.id).filter(TaskRun.workflow_run_id == wr.id, Approval.status == "WAITING"):
            approval.status, approval.decided_at = "CANCELLED", now()
            for artifact_review in db.query(ArtifactReview).filter_by(approval_id=approval.id):
                artifact_review.status = "CANCELLED"
        current = latest_attempts(db, wr.id)
        ids = [rid for t in current.values() if (rid := cancel_task(db, t, workflow_cancel=True))]
        aggregate(db, wr, current)
        db.commit()
    await interrupt_many(ids)
    return get_execution(workflow_run_id)


@router.post("/task-runs/{task_run_id}/cancel", status_code=202)
async def cancel_attempt(task_run_id: str):
    with COMMAND_LOCK, Session() as db:
        t = row(db, TaskRun, task_run_id)
        if latest_attempts(db, t.workflow_run_id)[t.task_definition_id].id != t.id:
            raise HTTPException(409, "Only the current Task attempt can be cancelled or abandoned")
        rid = cancel_task(db, t)
        db.commit()
    await interrupt_many([rid] if rid else [])
    return get_execution(t.workflow_run_id)


@router.post("/task-runs/{task_run_id}/retry", status_code=202)
def retry_attempt(task_run_id: str, http: HttpRequest):
    with COMMAND_LOCK, Session() as db:
        t = retry_task(db, row(db, TaskRun, task_run_id), http.headers.get("idempotency-key"))
        db.commit()
        runner.wake.set()
        return dump(t)


@router.post("/task-runs/{task_run_id}/branch", status_code=202)
async def branch_attempt(task_run_id: str, body: BranchBody, http: HttpRequest):
    key = http.headers.get("idempotency-key")
    with Session() as db:
        existing, ckey, digest = command(db, WorkflowRun, f"branch:{task_run_id}", key, body.model_dump())
        if existing:
            return detail(db, existing)
        source = row(db, TaskRun, task_run_id)
        parent = row(db, WorkflowRun, source.workflow_run_id)
        snapshot = copy.deepcopy(json.loads(parent.definition_snapshot))
        original = next(t for t in snapshot["tasks"] if t["id"] == source.task_definition_id)
    catalog = await catalog_from(runner.gateway)
    profile = resolve(catalog, original.get("execution_profile") or legacy_profile(original["model"], original["reasoning"]), override(body))
    worker_profile(profile)
    original["execution_profile"] = profile
    original["model"], original["reasoning"] = profile["model"], profile["reasoning"]
    with COMMAND_LOCK, Session() as db:
        existing, ckey, digest = command(db, WorkflowRun, f"branch:{task_run_id}", key, body.model_dump())
        if existing:
            return detail(db, existing)
        source = row(db, TaskRun, task_run_id)
        parent = row(db, WorkflowRun, source.workflow_run_id)
        work = row(db, Work, parent.work_id)
        safe_to_start(db, work)
        if source.status != "COMPLETED":
            raise HTTPException(409, "Branch requires a completed Task")
        out = {o.output_key: o.artifact_id for o in db.query(TaskRunOutput).filter_by(task_run_id=source.id)}
        selected = body.source_output_keys if body.source_output_keys is not None else list(out)
        if not selected or not set(selected).issubset(out):
            raise HTTPException(422, "Select existing output slots")
        original["instruction"], original["depends_on"] = body.instruction, []
        original["input_rule"] = [{"input_key": "branch_" + str(i), "artifact_id": out[k]} for i, k in enumerate(selected)]
        for i, binding in enumerate(db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=source.id)):
            original["input_rule"].append({"input_key": "prior_" + str(i), "artifact_id": binding.source_artifact_id})
        for b in original["input_rule"]:
            a = admit_artifact(db, b["artifact_id"], work, verify=True)
            snapshot.setdefault("artifact_hashes", {})[a.id] = a.sha256
        if body.output_rule is not None:
            original["output_rule"] = [o.model_dump() for o in body.output_rule]
        # Branch must obey the same unique path/slot rules as a saved Task.
        TaskBody.model_validate({key: original[key] for key in TaskBody.model_fields if key in original})
        slot_keys = {o["output_key"] for o in outputs(original)}
        if not set(body.revision_of).issubset(slot_keys) or not set(body.revision_of.values()).issubset(set(out[k] for k in selected)):
            raise HTTPException(422, "Revision mapping must link a selected original to a declared output")
        original["revision_of"] = body.revision_of
        original["history_mode"] = body.history_mode
        original.pop("fork_thread_id", None)
        original.pop("fork_turn_id", None)
        if body.history_mode == "FORK":
            source_run = db.get(Run, source.run_id)
            if source_run.model != original["model"] or not source_run.thread_id:
                raise HTTPException(409, "Fork requires the same model and a saved Thread")
            active = db.query(Run).filter(Run.thread_id == source_run.thread_id, Run.status.in_(["CREATED", "RUNNING"])).first()
            if active:
                raise HTTPException(409, "Source conversation is active")
            original.update(fork_thread_id=source_run.thread_id, fork_turn_id=source_run.turn_id)
        snapshot["tasks"] = [original]
        wr = new_execution(db, row(db, WorkflowDefinition, parent.workflow_definition_id), snapshot, ckey, digest, parent, source)
        add_branch = next(iter(latest_attempts(db, wr.id).values()))
        task_event(db, add_branch, "BRANCH_CREATED", {"parent_task_run_id": source.id, "history_mode": body.history_mode})
        db.commit()
        runner.wake.set()
        return detail(db, wr)


@router.get("/workflow-runs/{workflow_run_id}/events")
async def workflow_events(workflow_run_id: str, request: HttpRequest):
    with Session() as db:
        row(db, WorkflowRun, workflow_run_id)
    try:
        last = max(0, int(request.headers.get("last-event-id", request.query_params.get("after", "0"))))
    except ValueError:
        raise HTTPException(400, "Invalid event cursor")
    async def stream():
        cursor = last
        while not await request.is_disconnected():
            with Session() as db:
                read_snapshot(db)
                events = [(e.id, e.type, e.payload) for e in db.query(Event).filter(Event.workflow_run_id == workflow_run_id, Event.id > cursor).order_by(Event.id).limit(100)]
                terminal = db.get(WorkflowRun, workflow_run_id).status not in {"CREATED", "RUNNING", "WAITING_APPROVAL", "PAUSED"}
            for eid, kind, payload in events:
                cursor = eid
                yield f"id: {eid}\nevent: {kind}\ndata: {payload}\n\n"
            if terminal and not events:
                break
            if not events:
                yield ": heartbeat\n\n"
                await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/artifacts/{artifact_id}/publish")
def publish_artifact(artifact_id: str, body: PublishBody):
    with COMMAND_LOCK, Session() as db:
        publication = publish(db, artifact_id, body.scope)
        db.commit()
        remove_published_staging(db.get(Artifact, artifact_id))
        return dump(publication)


@router.get("/library")
def get_library(work_id: str, scope: Literal["WORK", "CATEGORY", "GLOBAL"] | None = None):
    with Session() as db:
        return library(db, row(db, Work, work_id), scope)


@router.get("/artifacts/{artifact_id}/lineage")
def lineage(artifact_id: str, offset: int = 0, limit: int = 100, after: str | None = None):
    with Session() as db:
        row(db, Artifact, artifact_id)
        relations = db.query(ArtifactRelation).filter((ArtifactRelation.source_artifact_id == artifact_id) | (ArtifactRelation.target_artifact_id == artifact_id))
        if after:
            relations = relations.filter(ArtifactRelation.id > after)
        relations = relations.order_by(ArtifactRelation.id).offset(max(0, offset)).limit(min(max(1, limit), 100))
        return [{**dump(r), "source": dump(db.get(Artifact, r.source_artifact_id)),
                 "target": dump(db.get(Artifact, r.target_artifact_id)) if r.target_artifact_id else None,
                 "consumer": dump(db.get(TaskRun, r.target_task_run_id)) if r.target_task_run_id else None} for r in relations]


@router.post("/workflows/{workflow_id}/templates", status_code=201)
def save_template(workflow_id: str, body: TemplateBody):
    with COMMAND_LOCK, Session() as db:
        data = definition(db, workflow_id)
        t = WorkflowTemplate(id=ident("tpl"), name=body.name or data["name"], description=body.description,
                             source_workflow_definition_id=workflow_id, snapshot=encode(data))
        db.add(t)
        db.commit()
        return dump(t)


@router.get("/workflow-templates")
def templates():
    with Session() as db:
        return [dump(t) for t in db.query(WorkflowTemplate).order_by(WorkflowTemplate.created_at)]


@router.post("/workflow-templates/{template_id}/clone", status_code=201)
def clone_template(template_id: str, body: CloneBody):
    with COMMAND_LOCK, Session() as db:
        template = row(db, WorkflowTemplate, template_id)
        work = row(db, Work, body.target_work_id)
        data = json.loads(template.snapshot)
        mapping = {t["id"]: ident("task") for t in data["tasks"]}
        unresolved = [{**b, "task_id": mapping[b["task_id"]]} for b in data.get("unresolved_bindings", [])
                      if b.get("task_id") in mapping]
        for t in data["tasks"]:
            t["id"] = mapping[t["id"]]
            t["depends_on"] = [mapping[p] for p in t["depends_on"]]
            cr = t["context_rule"]
            keep_sources = []
            for sid in cr["source_ids"]:
                s = db.get(Source, sid)
                if s and s.work_id == work.id:
                    keep_sources.append(sid)
                else:
                    unresolved.append({"task_id": t["id"], "source_id": sid, "name": s.name if s else sid})
            cr["source_ids"] = keep_sources
            for group, bindings in [("context", cr["artifact_ids"]), ("input", t["input_rule"])]:
                keep = []
                for b in bindings:
                    aid = b if group == "context" else b.get("artifact_id")
                    if aid:
                        try:
                            admit_artifact(db, aid, work)
                        except ValueError:
                            a = db.get(Artifact, aid)
                            unresolved.append({"task_id": t["id"], "binding": b, "name": a.name if a else aid})
                            continue
                    elif group == "input":
                        b["task_definition_id"] = mapping[b["task_definition_id"]]
                    keep.append(b)
                if group == "context":
                    cr["artifact_ids"] = keep
                else:
                    t["input_rule"] = keep
            if t["workspace_mode"] == "GIT_WORKTREE" and not work.linked_workspace_path:
                unresolved.append({"task_id": t["id"], "workspace_mode": "GIT_WORKTREE"})
                t["workspace_mode"] = "ARTIFACT_ONLY"
        wf_body = WorkflowBody(name=template.name, description=template.description, enabled=not unresolved,
                               tasks=data["tasks"], unresolved_bindings=unresolved)
        wf = save_definition(db, work, wf_body)
        db.commit()
        return definition(db, wf.id)


@router.post("/works/{work_id}/sources/import", status_code=201)
def import_sources(work_id: str, body: ImportBody):
    from pathlib import Path
    from .git_workspace import linked_path
    with COMMAND_LOCK, Session() as db:
        work = row(db, Work, work_id)
        if work.archived:
            raise HTTPException(409, "Choose an active Work")
        root = workspace_root(work)
        if work.linked_workspace_path:
            root = Path(linked_path(work.linked_workspace_path))
        if work.storage_layout == "EXTERNAL":
            sources = [register_reference(db, work, root, name, "WORKSPACE") for name in body.paths]
        else:
            sources = [register_source(Path(work.path), work.id, Path(name).name, safe_read(root, name),
                                       "application/octet-stream", True, db) for name in body.paths]
        db.commit()
        return [dump(s) for s in sources]
