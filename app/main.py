import asyncio
import html
import json
import os
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import bleach
import markdown
from fastapi import FastAPI, File, Form, HTTPException, Request as HttpRequest, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from .config import MAX_PREVIEW, SESSION_PATH, STATIC_DIR, UPLOAD_LIMIT
from .db import Artifact, Category, Event, Instruction, Request, Run, Session, Source, Work, TaskRun, add_event, dump, now, read_snapshot
from .gateway import error_text
from .runner import Runner
from .workspace import ident, provision_work, register_source, safe_child, safe_read, sha, work_dir

from .run_service import create_run
from .artifact_service import admit_artifact
from .git_workspace import linked_path
from .workflow_api import configure
from .storage import create_workspace, workspace_root, location_root, file_bytes
from .storage_api import router as storage_router
from .execution_settings import ExecutionProfile, catalog_from, inherited, override, resolve
from .execution_settings_api import configure as configure_settings
from .workflow_operations_api import configure as configure_operations, monitoring

runner = Runner()


class CategoryBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class WorkBody(CategoryBody):
    category_id: str
    workspace_kind: Literal["MANAGED", "LINKED"] = "MANAGED"
    linked_workspace_path: str | None = None
    workspace_mode: Literal["NEW", "LINKED"] | None = None
    workspace_folder: str | None = None
    workspace_root: str | None = None
    workspace_path: str | None = None
    description: str = Field(default="", max_length=10000)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        return CategoryBody.nonblank(value) if value is not None else None


class WorkUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    archived: bool | None = None


class ModelBody(BaseModel):
    model: str | None = None
    reasoning: str | None = None
    execution_profile: ExecutionProfile | None = None


class ExecuteBody(ModelBody):
    instruction: str = Field(min_length=1, max_length=30000)
    context_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)
    exclude_resource_ids: list[str] = Field(default_factory=list, max_length=100)
    pack_id: str | None = None
    budget: int = Field(default=40000, ge=100, le=1000000)
    allow_over_budget: bool = False
    context_policies: dict[str, Literal['REFERENCE','RETRIEVE','FULL']] = Field(default_factory=dict, max_length=300)

    @field_validator("instruction")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Instruction cannot be blank")
        return value


class SteerBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=10000)


def ensure_token():
    try:
        fd = os.open(SESSION_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as output:
            output.write(secrets.token_urlsafe(32))
    return SESSION_PATH.read_text().strip()


def get_row(db, cls, row_id):
    row = db.get(cls, row_id)
    if not row:
        raise HTTPException(404, f"{cls.__name__} not found")
    return row


def queue_run(db, work, instruction, context_ids, model, reasoning, http, operation="new", parent=None, request=None, artifact_ids=None,
              execution_profile=None, input_override=None, catalog=None, context_config=None, conversation=None, commit=True, command_identity=None, frozen_context=None):
    artifact_ids = artifact_ids or []
    connection = db.connection()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    key = http.headers.get("idempotency-key")
    if key and len(key) > 160:
        raise HTTPException(400, "Idempotency key too long")
    fingerprint = sha(json.dumps([work.id, operation, parent.id if parent else None, instruction, context_ids, artifact_ids,
                                 input_override if input_override is not None else {"model": model, "reasoning": reasoning}, context_config], sort_keys=True).encode())
    key = f"{work.id}:{operation}:{key}" if key else None
    if command_identity:
        key, fingerprint = command_identity
    if key:
        existing = db.query(Run).filter_by(command_key=key).first()
        if existing:
            if existing.command_hash != fingerprint:
                raise HTTPException(409, "Idempotency key was used with different input")
            return existing
    if catalog is not None:
        execution_profile = resolve(catalog, inherited(db, work), input_override, status_code=400)
        model, reasoning = execution_profile["model"], execution_profile["reasoning"]
    if execution_profile:
        from .workflow_operations import worker_profile
        worker_profile(execution_profile)
    if work.archived or work.provision_state != "READY":
        raise HTTPException(409, "Work is archived or not ready")
    if not get_row(db,Category,work.category_id).active:
        raise HTTPException(409,"비활성 Category에서는 실행할 수 없습니다. 관리 화면에서 다시 활성화하세요.")
    if db.query(Run).filter(Run.safety_block.is_(True)).first():
        raise HTTPException(409, "A Runtime outcome is unknown. Reconcile that Run before starting another.")
    if parent and operation == "resume":
        from .conversation import thread_for_run
        conversation_parent = thread_for_run(db, parent)
        if parent.is_query or conversation_parent.status in {"EPHEMERAL", "CLOSED", "SUPERSEDED"}:
            raise HTTPException(409, "This conversation cannot continue; use explicit promotion or fresh context")
        if conversation_parent.compact_state in {"RUNNING", "UNKNOWN"}:
            raise HTTPException(409, "Resolve compaction outcome or use a fresh Handoff")
        if not parent.thread_id or parent.status in {"CREATED", "RUNNING"}:
            raise HTTPException(409, "Resume requires a terminal Run with a Thread")
        if db.query(Run).filter(Run.thread_id == parent.thread_id, Run.status.in_(["CREATED", "RUNNING"])).first():
            raise HTTPException(409, "This Thread already has a queued or active Run")
    allowed = {s.id for s in db.query(Source).filter_by(work_id=work.id)} if frozen_context is None else set(context_ids)
    if len(set(context_ids)) != len(context_ids) or not set(context_ids).issubset(allowed):
        raise HTTPException(400, "Invalid Context selection")
    if len(set(artifact_ids)) != len(artifact_ids):
        raise HTTPException(400, "Duplicate Artifact selection")
    for aid in artifact_ids if frozen_context is None else []:
        try:
            admit_artifact(db, aid, work)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    run = create_run(db, work.id, instruction, context_ids, artifact_ids, model, reasoning,
                     operation=operation, parent=parent, request=request, command_key=key, command_hash=fingerprint,
                     execution_profile=execution_profile, context_config=context_config, conversation=conversation, frozen_context=frozen_context)
    add_event(db, run.id, "ACTIVITY", {"message": "Request queued"})
    if commit:
        db.commit()
        runner.wake.set()
    return run


@asynccontextmanager
async def lifespan(app):
    ensure_token()
    await runner.start()
    try:
        yield
    finally:
        await runner.close()


app = FastAPI(title="AI Project Control Center", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(configure(runner))
app.include_router(storage_router)
app.include_router(configure_settings(runner))
app.include_router(configure_operations(runner))
from .conversation_api import configure as configure_conversations
app.include_router(configure_conversations(runner, queue_run))
from .operations_api import configure as configure_dashboard, dashboard_data
from .work_tools_api import configure as configure_work_tools
app.include_router(configure_dashboard(runner))
app.include_router(configure_work_tools(runner, queue_run))
from .request_queue import configure as configure_request_queue
app.include_router(configure_request_queue(runner, queue_run))
from .flow_plans_api import configure as configure_flow_plans
app.include_router(configure_flow_plans(runner, queue_run))


@app.exception_handler(ValueError)
async def validation_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return JSONResponse({"detail": "Conflicting name or command; reload and retry"}, status_code=409)


@app.middleware("http")
async def local_session_guard(request, call_next):
    peer = request.client.host if request.client else ""
    host = urllib.parse.urlparse("//" + request.headers.get("host", "")).hostname
    if peer not in {"127.0.0.1", "::1", "testclient"} or host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return JSONResponse({"detail": "Loopback access only"}, status_code=403)
    if request.url.path.startswith("/api/"):
        token = ensure_token()
        if not secrets.compare_digest(request.cookies.get("cc_session", ""), token):
            return JSONResponse({"detail": "Local session required"}, status_code=401)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = urllib.parse.urlparse(request.headers.get("origin", ""))
            if origin.scheme != request.url.scheme or origin.netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Same-origin request required"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-control-token", ""), token):
                return JSONResponse({"detail": "Request token required"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", response_class=HTMLResponse)
def home():
    page = (STATIC_DIR / "index.html").read_text().replace("__CONTROL_TOKEN__", ensure_token())
    response = HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
    response.set_cookie("cc_session", ensure_token(), httponly=True, samesite="strict", path="/")
    return response


@app.get("/api/health")
async def health():
    return {"ok": runner.dispatch_error is None and runner.task is not None and not runner.task.done(),
            "dispatcher_error": runner.dispatch_error, "account": await runner.gateway.account(),
            "login": runner.gateway.login_state, "max_parallel_tasks": runner.max_parallel_tasks}


@app.post("/api/login")
async def login():
    await runner.gateway.open()
    try:
        return await runner.gateway.login()
    except Exception as exc:
        raise HTTPException(503, error_text(exc))


@app.delete("/api/login")
async def cancel_login():
    await runner.gateway.cancel_login()
    return runner.gateway.login_state


@app.get("/api/models")
async def models():
    try:
        return await runner.gateway.models()
    except Exception as exc:
        raise HTTPException(503, error_text(exc))


@app.get("/api/dashboard")
async def dashboard():
    return await dashboard_data(legacy=True)


@app.post("/api/categories", status_code=201)
def create_category(body: CategoryBody):
    with Session() as db:
        row = Category(id=ident("cat"), name=body.name)
        db.add(row)
        db.commit()
        return dump(row)


@app.patch("/api/categories/{category_id}")
def rename_category(category_id: str, body: CategoryUpdate):
    with Session() as db:
        row = get_row(db, Category, category_id)
        if body.name is not None: row.name = body.name
        if body.active is not None: row.active = body.active
        db.commit()
        return dump(row)


@app.delete("/api/categories/{category_id}")
def deactivate_category(category_id: str):
    with Session() as db:
        row = get_row(db, Category, category_id)
        row.active = False
        db.commit()
        return dump(row)


@app.post("/api/works", status_code=201)
def create_work(body: WorkBody):
    with Session() as db:
        category = get_row(db, Category, body.category_id)
        if not category.active:
            raise HTTPException(409, "Category is inactive")
        if body.workspace_mode == "LINKED" or body.workspace_kind == "LINKED":
            selected = body.workspace_path or body.linked_workspace_path
            if not selected:
                raise HTTPException(422, "Linked workspace path required")
            project = linked_path(selected)
        else:
            if body.linked_workspace_path or body.workspace_path:
                raise HTTPException(422, "Managed Work cannot specify linked path")
            project = str(create_workspace(body.workspace_folder or body.name, body.workspace_root))
        work_id = ident("work")
        row = Work(id=work_id, category_id=category.id, name=body.name, description=body.description,
                   path=project, workspace_kind="LINKED", linked_workspace_path=project,
                   workspace_path=project, storage_layout="EXTERNAL")
        db.add(row)
        db.commit()
        provision_work(row)
        row.provision_state = "READY"
        db.commit()
        return dump(row)


@app.patch("/api/works/{work_id}")
def update_work(work_id: str, body: WorkUpdate):
    with Session() as db:
        row = get_row(db, Work, work_id)
        for key, value in body.model_dump(exclude_none=True).items():
            if key == "name" and not value.strip():
                raise HTTPException(400, "Name cannot be blank")
            setattr(row, key, value)
        db.commit()
        provision_work(row)
        return dump(row)


@app.get("/api/works/{work_id}")
def work_detail(work_id: str):
    with Session() as db:
        work = get_row(db, Work, work_id)
        candidates = []
        for a in db.query(Artifact).filter_by(work_id=work.id):
            try:
                admit_artifact(db, a.id, work)
            except ValueError:
                continue
            candidates.append(dump(a))
        return {"work": dump(work), "category": dump(get_row(db,Category,work.category_id)), "artifact_candidates": candidates, **{name: [dump(x) for x in db.query(cls).filter_by(work_id=work.id).order_by(cls.created_at.desc())]
                for name, cls in [("sources", Source), ("requests", Request), ("runs", Run), ("artifacts", Artifact)]},
                "runs": [dump(x) for x in db.query(Run).filter_by(work_id=work.id,is_query=False).order_by(Run.created_at.desc())],
                "requests": [dump(x) for x in db.query(Request).filter_by(work_id=work.id).filter(~Request.id.in_(db.query(Run.request_id).filter_by(is_query=True))).order_by(Request.created_at.desc())]}


@app.post("/api/works/{work_id}/sources", status_code=201)
async def upload(work_id: str, file: UploadFile = File(...), context: bool = Form(True)):
    content = await file.read(UPLOAD_LIMIT + 1)
    with Session() as db:
        work = get_row(db, Work, work_id)
        if work.archived:
            raise HTTPException(409, "Work is archived")
        try:
            root = workspace_root(work) if work.storage_layout == "EXTERNAL" else Path(work.path)
            row = register_source(root, work.id, file.filename or "upload", content, file.content_type, context, db,
                                  location_type="WORKSPACE" if work.storage_layout == "EXTERNAL" else "LEGACY")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        return dump(row)


@app.get("/api/works/{work_id}/directory")
def directory(work_id: str):
    with Session() as db:
        work = get_row(db, Work, work_id)
        return {"path": str(workspace_root(work)), "workspace_kind": work.workspace_kind,
                "workspace_path": str(workspace_root(work)), "linked_workspace_path": work.linked_workspace_path,
                "storage_layout": work.storage_layout, "files": [dump(s) for s in db.query(Source).filter_by(work_id=work.id)]}


@app.get("/api/sources/{source_id}/download")
def source_download(source_id: str):
    with Session() as db:
        source = get_row(db, Source, source_id)
        work = get_row(db, Work, source.work_id)
        try:
            content = file_bytes(work, source, UPLOAD_LIMIT)
        except (ValueError, OSError):
            raise HTTPException(410, "Source unavailable")
        return download_bytes(content, source.name)


@app.post("/api/works/{work_id}/runs", status_code=202)
async def execute(work_id: str, body: ExecuteBody, http: HttpRequest):
    catalog = await catalog_from(runner.gateway)
    input_override = override(body)
    with Session() as db:
        work = get_row(db, Work, work_id)
        return dump(queue_run(db, work, body.instruction, body.context_ids, None, None, http,
                              artifact_ids=body.artifact_ids, input_override=input_override, catalog=catalog,
                              context_config={k: getattr(body,k) for k in ('resource_ids','exclude_resource_ids','pack_id','budget','allow_over_budget','context_policies')}))


@app.post("/api/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str, body: ExecuteBody, http: HttpRequest):
    catalog = await catalog_from(runner.gateway)
    input_override = override(body)
    with Session() as db:
        parent = get_row(db, Run, run_id)
        if db.query(TaskRun).filter_by(run_id=parent.id).first():
            raise HTTPException(409, "Use Task Branch/Retry for Workflow executions")
        work = get_row(db, Work, parent.work_id)
        return dump(queue_run(db, work, body.instruction, body.context_ids,
                              None, None, http, "resume", parent, artifact_ids=body.artifact_ids,
                              input_override=input_override, catalog=catalog,
                              context_config={k: getattr(body,k) for k in ('resource_ids','exclude_resource_ids','pack_id','budget','allow_over_budget','context_policies')}))


@app.post("/api/requests/{request_id}/retry", status_code=202)
async def retry(request_id: str, body: ModelBody, http: HttpRequest):
    catalog = await catalog_from(runner.gateway)
    input_override = override(body)
    with Session() as db:
        request = get_row(db, Request, request_id)
        if db.query(Run).filter_by(request_id=request.id, is_query=True).first():
            raise HTTPException(409, "Use a new ephemeral query instead of retrying temporary history")
        if db.query(Run.id).filter_by(request_id=request.id, operation="reference").first():
            raise HTTPException(409, "Manual file registration has no model execution to retry")
        if db.query(TaskRun).join(Run, TaskRun.run_id == Run.id).filter(Run.request_id == request.id).first():
            raise HTTPException(409, "Use Task Retry for Workflow executions")
        work = get_row(db, Work, request.work_id)
        return dump(queue_run(db, work, request.instruction,
                              json.loads(request.context_ids), None, None, http, "retry", request=request,
                              artifact_ids=json.loads(request.artifact_ids), input_override=input_override, catalog=catalog))


@app.get("/api/requests/{request_id}")
def request_detail(request_id: str):
    with Session() as db:
        row = get_row(db, Request, request_id)
        return {"request": dump(row), "runs": [dump(r) for r in db.query(Run).filter_by(request_id=row.id)]}


@app.post("/api/runs/{run_id}/steer", status_code=202)
async def steer(run_id: str, body: SteerBody):
    with Session() as db:
        run = get_row(db, Run, run_id)
        if run.status != "RUNNING" or run.phase != "EXECUTING" or run_id not in runner.gateway.handles:
            raise HTTPException(409, "Run has no active Turn")
        row = Instruction(run_id=run.id, turn_id=run.turn_id, text=body.instruction)
        db.add(row)
        db.commit()
        row_id = row.id
    try:
        await asyncio.wait_for(runner.gateway.steer(run_id, body.instruction), 20)
        delivery, error = "ACCEPTED", None
    except Exception as exc:
        delivery = "REJECTED" if type(exc).__name__ in {"InvalidRequestError", "ValueError"} else "DELIVERY_UNKNOWN"
        error = error_text(exc)
    with Session() as db:
        row = db.get(Instruction, row_id)
        row.delivery, row.error = delivery, error
        row.accepted_at = now() if delivery == "ACCEPTED" else None
        add_event(db, run_id, "ACTIVITY" if not error else "WARNING", {"instruction_id": row_id, "delivery": delivery, "message": error or "Additional instruction accepted"})
        db.commit()
        return JSONResponse(dump(row), status_code=202 if not error else 409)


@app.post("/api/runs/{run_id}/cancel", status_code=202)
async def cancel(run_id: str):
    with Session() as db:
        task = db.query(TaskRun).filter_by(run_id=run_id).first()
    if task:
        from .workflow_api import cancel_attempt
        await cancel_attempt(task.id)
        return run_detail(run_id)["run"]
    with Session() as db:
        run = get_row(db, Run, run_id)
        if run.status not in {"CREATED", "RUNNING"}:
            raise HTTPException(409, "Run is terminal")
        run.cancel_requested, run.cancel_reason = True, "user_cancel"
        if run.phase == "QUEUED":
            run.status, run.phase, run.completed_at = "CANCELLED", "CANCELLED", now()
            add_event(db, run_id, "RUN_CANCELLED", {"reason": "cancelled before dispatch"})
            from .conversation import finish_conversation
            finish_conversation(db, run)
        elif run.status == "RUNNING":
            run.phase = "CANCEL_REQUESTED"
        db.commit()
        result = dump(run)
    try:
        await asyncio.wait_for(runner.gateway.interrupt(run_id), 10)
    except Exception as exc:
        runner.emit(run_id, "WARNING", {"message": "Interrupt unconfirmed: " + error_text(exc)})
    runner.wake.set()
    return result


@app.post("/api/runs/{run_id}/reconcile")
async def reconcile(run_id: str):
    with Session() as db:
        row = get_row(db, Run, run_id)
        if not row.safety_block:
            raise HTTPException(409, "Run does not require reconciliation")
    await runner.gateway.open()
    await runner.reconcile(run_id)
    runner.wake.set()
    return run_detail(run_id)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str, after: int = 0):
    with Session() as db:
        read_snapshot(db)
        run = get_row(db, Run, run_id)
        task = db.query(TaskRun).filter_by(run_id=run_id).first()
        return {"run": {**dump(run), "task_run_id": task.id if task else None, "workflow_run_id": task.workflow_run_id if task else None}, "request": dump(db.get(Request, run.request_id)),
                "events": [{**dump(e), "payload": json.loads(e.payload)} for e in db.query(Event).filter(Event.run_id==run_id,Event.id>max(0,after)).order_by(Event.id)],
                "instructions": [dump(i) for i in db.query(Instruction).filter_by(run_id=run_id)],
                "artifacts": [dump(a) for a in db.query(Artifact).filter_by(run_id=run_id)]}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: HttpRequest):
    with Session() as db:
        get_row(db, Run, run_id)
    try:
        last = max(0, int(request.headers.get("last-event-id", request.query_params.get("after", "0"))))
    except ValueError:
        raise HTTPException(400, "Invalid event cursor")

    async def stream():
        cursor = last
        while not await request.is_disconnected():
            with Session() as db:
                read_snapshot(db)
                rows = [(e.id, e.type, e.payload) for e in db.query(Event).filter(Event.run_id == run_id, Event.id > cursor).order_by(Event.id).limit(100)]
                terminal = db.get(Run, run_id).status not in {"CREATED", "RUNNING"}
            for event_id, kind, payload in rows:
                cursor = event_id
                yield f"id: {event_id}\nevent: {kind}\ndata: {payload}\n\n"
            if terminal and not rows:
                break
            if not rows:
                yield ": heartbeat\n\n"
                await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


def verified_artifact(db, artifact_id):
    row = get_row(db, Artifact, artifact_id)
    work = db.get(Work, row.work_id)
    try:
        data = file_bytes(work, row)
        row.availability = "AVAILABLE" if len(data) == row.size and sha(data) == row.sha256 else "MODIFIED"
    except (OSError, ValueError):
        data, row.availability = None, "MISSING"
    db.commit()
    return row, work, data


@app.get("/api/artifacts/{artifact_id}")
def artifact_detail(artifact_id: str):
    with Session() as db:
        row, work, _ = verified_artifact(db, artifact_id)
        return {**dump(row), "local_path": str(location_root(work, row) / row.relative_path)}


def download_bytes(data, name):
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name),
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@app.get("/api/artifacts/{artifact_id}/download")
@app.get("/api/artifacts/{artifact_id}/preview")
def artifact_content(artifact_id: str, request: HttpRequest):
    with Session() as db:
        row, work, data = verified_artifact(db, artifact_id)
        if row.availability != "AVAILABLE":
            raise HTTPException(410, "Artifact " + row.availability.lower())
        if request.url.path.endswith("download") or len(data) > MAX_PREVIEW:
            return download_bytes(data, row.name)
        suffix = Path(row.name).suffix.lower()
        headers = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}
        if row.content_type in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            return Response(data, media_type=row.content_type, headers=headers)
        if suffix in {".md", ".markdown"}:
            rendered = markdown.markdown(data.decode("utf-8", errors="replace"), extensions=["fenced_code", "tables"])
            safe = bleach.clean(rendered, tags={"p", "h1", "h2", "h3", "h4", "pre", "code", "strong", "em", "ul", "ol", "li", "a", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "hr", "br"}, attributes={}, strip=True)
        elif row.content_type.startswith("text/") or suffix in {".py", ".js", ".ts", ".tsx", ".java", ".json", ".yaml", ".yml", ".xml", ".sh", ".svg"}:
            safe = "<pre>" + html.escape(data.decode("utf-8", errors="replace")) + "</pre>"
        else:
            return download_bytes(data, row.name)
        return HTMLResponse("<!doctype html><meta charset=utf-8><style>body{font:16px system-ui;margin:24px;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>" + safe, headers=headers)


def run():
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), workers=1)


if __name__ == "__main__":
    run()
