"""Persistent bounded Run pool shared by standalone requests and Workflow tasks."""
import asyncio
import json
import logging
from pathlib import Path

from .config import STATE_DIR, MAX_PARALLEL_TASKS
from .db import Artifact, Category, Event, Instruction, Request, Run, Session, Source, Work, TaskRun, WorkflowRun, ArtifactRelation, add_event, migrate, now
from .gateway import CodexGateway, error_text
from .execution import prepare_execution
from .workflow import COMMAND_LOCK, task_event, encode, latest_attempts
from .scheduler import tick, start_workflow
from .task_runner import contract, settle, task_spec
from .workspace import collect_artifacts, prepare_context, provision_work, safe_child, safe_read, save_manifest, sha
from .storage import runtime_root

TERMINAL = {"completed": "COMPLETED", "failed": "FAILED", "interrupted": "CANCELLED"}


class Runner:
    def __init__(self):
        self.gateway = CodexGateway()
        self.task = None
        self.stop = asyncio.Event()
        self.wake = asyncio.Event()
        self.lock_file = None
        self.active_tasks = {}
        self.owned_threads = {}
        self.max_parallel_tasks = MAX_PARALLEL_TASKS
        self.dispatch_error = None

    async def start(self):
        import fcntl
        # Lifespan can be entered again with a different loop (offline tests/restart).
        self.stop = asyncio.Event()
        self.wake = asyncio.Event()
        self.lock_file = open(STATE_DIR / "backend.lock", "a+")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            migrate()
            from .conversation import expire_queries
            with Session() as db:
                expire_queries(db)
                db.commit()
            await self.gateway.open()
            await self.recover()
            self.task = asyncio.create_task(self.dispatch())
        except BaseException:
            self.lock_file.close()
            raise

    async def close(self):
        self.stop.set()
        self.wake.set()
        if self.task:
            await self.task
        ids = list(self.active_tasks)
        with Session() as db:
            for rid in ids:
                run = db.get(Run, rid)
                if run.status in {"CREATED", "RUNNING"}:
                    run.cancel_requested, run.cancel_reason = True, "backend_shutdown"
            db.commit()
        await asyncio.gather(*(self._interrupt(rid) for rid in ids), return_exceptions=True)
        active = list(self.active_tasks.values())
        if active:
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.gather(*active, return_exceptions=True)), 15)
            except asyncio.TimeoutError:
                for task in active:
                    task.cancel()
                await asyncio.gather(*active, return_exceptions=True)
        await self.gateway.close()
        if self.lock_file:
            self.lock_file.close()

    async def _interrupt(self, rid):
        await asyncio.wait_for(self.gateway.interrupt(rid), 5)

    def emit(self, run_id, kind, payload):
        with Session() as db:
            from .db import ThreadRecord
            run = db.get(Run, run_id)
            if run.conversation_id and kind in {"CONTEXT_USAGE", "CONTEXT_COMPACTED"}:
                thread = db.get(ThreadRecord, run.conversation_id)
                if kind == "CONTEXT_USAGE": thread.usage = json.dumps(payload)
                else: thread.compact_state = "COMPLETED"
            if run.is_query and kind in {"ACTIVITY", "COMMAND_STARTED", "COMMAND_COMPLETED"}:
                payload = {"message": "임시 질문 실행 중", "sequence": payload.get("sequence")}
            event = add_event(db, run_id, kind, payload)
            db.commit()
            return event.id

    async def recover(self):
        with Session() as db:
            works = db.query(Work).filter(Work.provision_state != "READY").all()
            for work in works:
                try:
                    provision_work(work)
                    work.provision_state = "READY"
                except (OSError, ValueError):
                    work.provision_state = "ERROR"
            for instruction in db.query(Instruction).filter(Instruction.delivery == "PENDING"):
                instruction.delivery = "DELIVERY_UNKNOWN"
            incomplete_tasks = db.query(TaskRun.run_id).filter(TaskRun.status.in_(["QUEUED", "RUNNING"]), TaskRun.run_id.is_not(None))
            runs = db.query(Run).filter((Run.status == "RUNNING") | (Run.phase.in_(["PREPARING", "SUBMITTING", "FINALIZING"])) |
                                       Run.safety_block.is_(True) | ((Run.status == "COMPLETED") & Run.id.in_(incomplete_tasks))).all()
            db.commit()
        for run in runs:
            if run.phase == "PREPARING" and not run.turn_id:
                from .db import ThreadRecord
                with Session() as db:
                    thread = db.get(ThreadRecord, run.conversation_id) if run.conversation_id else None
                    if thread and thread.compact_state == "RUNNING":
                        thread.compact_state = "UNKNOWN"
                        db.commit()
                await asyncio.to_thread(self.finish, run.id, "failed", error={"code": "PREPARATION_INTERRUPTED"})
            else:
                await self.reconcile(run.id)

    async def reconcile(self, run_id):
        with Session() as db:
            run = db.get(Run, run_id)
            stored = run.runtime_status
        if stored in TERMINAL:
            await asyncio.to_thread(self.finish, run_id, stored)
            return
        try:
            if not run.thread_id:
                raise ValueError("No persisted Thread ID; automatic re-submission disabled")
            thread = await asyncio.wait_for(self.gateway.read_thread(run.thread_id), 20)
            if not run.turn_id:
                manifest = json.loads(run.manifest)
                matches = [t for t in thread.get("turns", [])
                           if manifest.get("prompt_sha256") in t.get("input_hashes", [])]
                if len(matches) != 1:
                    raise ValueError("No unique Turn matching the frozen prompt; automatic re-submission disabled")
                run.turn_id = matches[0]["id"]
                with Session() as db:
                    db.get(Run, run_id).turn_id = run.turn_id
                    db.commit()
            turn = next((t for t in thread.get("turns", []) if t["id"] == run.turn_id), None)
            if not turn or turn["status"] not in TERMINAL:
                raise ValueError("Runtime has no confirmed terminal status for this Turn")
            await asyncio.to_thread(self.finish, run_id, turn["status"], final=self.final_message(turn), error=turn.get("error"))
        except Exception as exc:
            self.unknown(run_id, error_text(exc))

    def unknown(self, run_id, message):
        with Session() as db:
            run = db.get(Run, run_id)
            run.status, run.phase, run.safety_block = "FAILED", "RECOVERING", True
            run.error = json.dumps({"code": "RUNTIME_OUTCOME_UNKNOWN", "message": message})
            run.completed_at = now()
            add_event(db, run_id, "WARNING", {"message": message, "safety_block": True})
            if not db.query(Event).filter_by(run_id=run_id, type="RUN_FAILED").first():
                add_event(db, run_id, "RUN_FAILED", {"status": "FAILED", "code": "RUNTIME_OUTCOME_UNKNOWN"})
            task = db.query(TaskRun).filter_by(run_id=run_id).first()
            if task:
                settle(db, task, run)
            db.commit()

    async def dispatch(self):
        while not self.stop.is_set():
            try:
                await self._dispatch_loop()
            except Exception as exc:
                # A rolled-back scheduler transaction must not kill the only
                # dispatcher. Active executions retain their slots and handles.
                self.dispatch_error = error_text(exc)
                logging.getLogger(__name__).exception("Dispatcher iteration failed")
                try:
                    await asyncio.wait_for(self.stop.wait(), 1)
                except asyncio.TimeoutError:
                    pass

    async def _dispatch_loop(self):
        last_expiry = 0
        while not self.stop.is_set():
            self.wake.clear()
            if asyncio.get_running_loop().time() - last_expiry > 60:
                def expire():
                    from .conversation import expire_queries
                    with COMMAND_LOCK, Session() as db:
                        expire_queries(db)
                        db.commit()
                await asyncio.to_thread(expire)
                last_expiry = asyncio.get_running_loop().time()
            from .workflow_triggers import dispatch_due
            await dispatch_due(self)
            await asyncio.to_thread(tick)
            self.dispatch_error = None
            with Session() as db:
                blocked = db.query(Run.id).filter_by(safety_block=True).first()
                rows = [] if blocked else db.query(Run).filter_by(status="CREATED", phase="QUEUED").order_by(Run.created_at, Run.id).all()
                standalone_active = any(not db.query(TaskRun.id).filter_by(run_id=rid).first() for rid in self.active_tasks)
                for run in rows:
                    work = db.get(Work,run.work_id)
                    if work.archived or not db.get(Category,work.category_id).active:
                        continue
                    if len(self.active_tasks) >= self.max_parallel_tasks:
                        break
                    if run.id in self.active_tasks:
                        continue
                    task = db.query(TaskRun).filter_by(run_id=run.id).first()
                    if task and db.get(WorkflowRun, task.workflow_run_id).paused:
                        continue
                    if not task and standalone_active:
                        continue
                    thread = run.thread_id
                    thread = thread or json.loads(run.context_config or "{}").get("fork_thread_id")
                    if task:
                        spec = task_spec(db.get(WorkflowRun, task.workflow_run_id), task)
                        thread = thread or spec.get("fork_thread_id")
                    if thread and thread in self.owned_threads:
                        continue
                    if thread:
                        self.owned_threads[thread] = run.id
                    if not task:
                        standalone_active = True
                    self.active_tasks[run.id] = asyncio.create_task(self._execute_owned(run.id))
            try:
                await asyncio.wait_for(self.wake.wait(), .2)
            except asyncio.TimeoutError:
                pass

    async def _execute_owned(self, run_id):
        try:
            await self.execute(run_id)
        finally:
            self.active_tasks.pop(run_id, None)
            for thread, owner in list(self.owned_threads.items()):
                if owner == run_id:
                    self.owned_threads.pop(thread, None)
            self.wake.set()

    async def execute(self, run_id):
        submitted = False
        thread_id = None
        try:
            with COMMAND_LOCK, Session() as db:
                from .execution_settings import run_profile
                from .workflow_operations import worker_profile
                worker_profile(run_profile(db.get(Run,run_id)))
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task:
                    from .workflow_operations import gate, worker_profile
                    wr = db.get(WorkflowRun, task.workflow_run_id)
                    if wr.paused:
                        return
                    spec = task_spec(wr, task)
                    current = latest_attempts(db, wr.id)
                    if any(current[p].status != "COMPLETED" or gate(db, current[p]) != "APPROVED" for p in spec["depends_on"]):
                        return
                    worker_profile(spec.get("execution_profile") or {})
                changed = db.query(Run).filter_by(id=run_id, status="CREATED", phase="QUEUED").update({Run.phase: "PREPARING"})
                if not changed:
                    db.rollback()
                    return
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task:
                    start_workflow(db, task)
                db.commit()
                run = db.get(Run, run_id)
                request, work = db.get(Request, run.request_id), db.get(Work, run.work_id)
                ids = [] if json.loads(run.context_config or '{}').get('queue_snapshot') else json.loads(request.context_ids)
                found = {s.id: s for s in db.query(Source).filter(Source.id.in_(ids), Source.work_id == run.work_id)}
                if len(found) != len(ids):
                    raise ValueError("Selected Context no longer exists")
                sources = [found[i] for i in ids]
            manifest = await asyncio.to_thread(prepare_execution, work, run, request, sources)
            with Session() as db:
                row = db.get(Run, run_id)
                row.manifest = json.dumps(manifest, ensure_ascii=False)
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task:
                    for f in manifest["files"] + manifest.get("context_aliases", []):
                        if f.get("artifact_id"):
                            rel = db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=task.id, input_key=f["input_key"]).one()
                            rel.snapshot_path = f["snapshot_path"]
                            task_event(db, task, "ARTIFACT_HANDOFF", f, suffix=f["input_key"])
                if row.cancel_requested:
                    db.commit()
                    await asyncio.to_thread(self.finish, run_id, "interrupted")
                    return
                db.commit()
            if manifest.get("project_path_inputs") and not manifest["project_path_inputs"].get("read_scope_enforced"):
                raise ValueError("PROJECT_PATH_SCOPE_UNENFORCED: Codex Runtime cannot restrict reads to the selected project paths")
            if manifest.get("compact_requested"):
                from .db import ThreadRecord
                history = await self.gateway.read_thread(run.thread_id)
                manifest["compact_before"] = [item for turn in history.get("turns", []) for item in turn.get("compactions", [])]
                with Session() as db:
                    db.get(ThreadRecord, run.conversation_id).compact_state = "RUNNING"
                    db.get(Run, run_id).manifest = json.dumps(manifest)
                    db.commit()
                try:
                    await self.gateway.compact_thread(run.thread_id, manifest["cwd"], run.model,
                        settings=manifest["sandbox"], rules=manifest["developer_instructions"], execution_profile=manifest["execution_profile"])
                except BaseException:
                    with Session() as db:
                        db.get(ThreadRecord, run.conversation_id).compact_state = "UNKNOWN"
                        db.commit()
                    raise
                with Session() as db:
                    db.get(ThreadRecord, run.conversation_id).compact_state = "COMPLETED"
                    db.commit()
                self.emit(run_id, "CONTEXT_COMPACTED", {"thread_id": run.thread_id, "explicit": True})
            if manifest.get("fork_thread_id") and not run.thread_id:
                history = await self.gateway.read_thread(manifest["fork_thread_id"])
                turns = history.get("turns", [])
                if not turns or turns[-1]["id"] != manifest["fork_turn_id"] or turns[-1]["status"] not in TERMINAL:
                    raise ValueError("Fork requires the selected Run to be the last terminal Turn")
                thread_id = await asyncio.wait_for(self.gateway.fork_thread(manifest["fork_thread_id"], manifest["cwd"], run.model,
                                                                         manifest["sandbox"], manifest["developer_instructions"],
                                                                         execution_profile=manifest["execution_profile"]), 30)
            else:
                thread_id = await asyncio.wait_for(self.gateway.thread(manifest["cwd"], run.model, run.thread_id,
                                                                       settings=manifest["sandbox"], rules=manifest["developer_instructions"],
                                                                       execution_profile=manifest["execution_profile"], ephemeral=manifest.get("ephemeral", False),
                                                                       research_read_network=manifest.get("research_read_network", False),
                                                                       requested_read_roots=manifest.get("project_path_inputs", {}).get("requested_runtime_read_roots")), 30)
            self.owned_threads[thread_id] = run_id
            manifest["thread_id"] = thread_id
            save_manifest(run_id, manifest)
            with Session() as db:
                row = db.get(Run, run_id)
                row.thread_id, row.manifest = thread_id, json.dumps(manifest, ensure_ascii=False)
                from .conversation import bind_runtime
                bind_runtime(db, row)
                cancelled = row.cancel_requested
                if not cancelled:
                    row.phase = "SUBMITTING"
                db.commit()
            if cancelled:
                await asyncio.to_thread(self.finish, run_id, "interrupted")
                return
            submitted = True
            accepted = await asyncio.wait_for(self.gateway.start_turn(run_id, thread_id, manifest["prompt"], run.model, run.reasoning,
                                                                     execution_profile=manifest["execution_profile"]), 45)
            with Session() as db:
                row = db.get(Run, run_id)
                row.turn_id, row.status, row.phase, row.started_at = accepted["turn_id"], "RUNNING", "EXECUTING", now()
                cancel = row.cancel_requested
                add_event(db, run_id, "RUN_STARTED", {"run_id": run_id, **accepted})
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task:
                    task.status, task.started_at = "RUNNING", row.started_at
                    task_event(db, task, "TASK_STARTED")
                db.commit()
            if cancel:
                await self.gateway.interrupt(run_id)
            terminal, final, seen, sequence = None, "", set(), 0
            async for event in self.gateway.events(run_id):
                sequence += 1
                kind = event["type"]
                if kind == "terminal":
                    terminal = event
                    with Session() as db:
                        row = db.get(Run, run_id)
                        row.runtime_status, row.phase = event["status"], "FINALIZING"
                        db.commit()
                    continue
                payload = event["payload"]
                item = payload.get("item_id")
                lifecycle = kind in {"COMMAND_STARTED", "COMMAND_COMPLETED", "file_hint"} or "text" in payload
                key = (kind, item)
                if lifecycle and item:
                    if key in seen:
                        continue
                    seen.add(key)
                if payload.get("phase") in {"final_answer", "final"}:
                    final = payload.get("text", "")
                if kind == "file_hint":
                    self.verify_hints(run_id, Path(manifest["cwd"]), payload)
                else:
                    self.emit(run_id, kind, {**payload, "sequence": sequence})
            if not terminal:
                await self.reconcile(run_id)
            else:
                await asyncio.to_thread(self.finish, run_id, terminal["status"], final=final, error=terminal.get("error"))
        except asyncio.CancelledError:
            if submitted:
                self.unknown(run_id, "Backend shutdown before terminal confirmation")
            else:
                await asyncio.to_thread(self.finish, run_id, "failed", error={"code": "PREPARATION_INTERRUPTED"})
            raise
        except Exception as exc:
            if submitted:
                self.emit(run_id, "WARNING", {"message": error_text(exc)})
                await self.reconcile(run_id)
            else:
                await asyncio.to_thread(self.finish, run_id, "failed", error={"code": "PREPARATION_FAILED", "message": error_text(exc)})
        finally:
            self.gateway.handles.pop(run_id, None)
            cleanup = getattr(self.gateway, 'release_research', None)
            if thread_id and callable(cleanup):
                await cleanup(thread_id)

    def verify_hints(self, run_id, workspace, payload):
        for name in payload["paths"]:
            path = Path(name)
            try:
                relative = str(path.relative_to(workspace)) if path.is_absolute() else name
                data = safe_read(workspace, relative)
                self.emit(run_id, "FILE_CHANGED", {"path": relative, "size": len(data), "sha256": sha(data), "origin": "runtime_hint"})
            except (ValueError, OSError):
                self.emit(run_id, "WARNING", {"message": "Runtime file hint not verified", "path": name})

    def finish(self, run_id, runtime_status, final="", error=None):
        # Files are verified outside a DB transaction; a shared lock prevents duplicate finalizers.
        with COMMAND_LOCK:
            with Session() as db:
                run = db.get(Run, run_id)
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task and task.status == "COMPLETED" and run.status == "COMPLETED":
                    return
                work = db.get(Work, run.work_id)
                manifest = json.loads(run.manifest)
                spec = task_spec(db.get(WorkflowRun, task.workflow_run_id), task) if task else None
                run.runtime_status, run.phase = runtime_status, "FINALIZING"
                if final:
                    run.final_text = final
                run.error = json.dumps(error, ensure_ascii=False) if error else None
                db.commit()
            status = TERMINAL.get(runtime_status, "FAILED")
            artifact_error, report, slots = None, None, {}
            try:
                root = runtime_root(work, manifest)
                workspace = safe_child(root, f"runs/{run_id}/workspace")
                output_root = Path(manifest["output_root"]) if manifest.get("output_root") else None
                if output_root:
                    safe_child(root, str(output_root.relative_to(root)))
                if manifest.get("workspace_mode") == "GIT_WORKTREE":
                    from .git_workspace import collect_changes
                    reserved = safe_child(output_root, "system")
                    with Session() as db:
                        already = db.query(Artifact).filter_by(run_id=run_id).first()
                    if not manifest.get("git_outputs_prepared"):
                        if reserved.exists() and not already:
                            raise ValueError("Worker wrote reserved system output namespace")
                        # Persist Backend ownership BEFORE writing reserved files.
                        # A crash between filesystem writes and Artifact row commit
                        # must allow deterministic regeneration on recovery.
                        manifest["git_outputs_prepared"] = True
                        with Session() as db:
                            db.get(Run, run_id).manifest = encode(manifest)
                            db.commit()
                        save_manifest(run_id, manifest)
                    collect_changes(work, manifest)
                    save_manifest(run_id, manifest)
                artifacts = collect_artifacts(root, work.id, run_id, workspace,
                                              partial=status != "COMPLETED", output_root=output_root,
                                              destination_root=manifest.get("workspace_root") if manifest.get("storage_layout") == "EXTERNAL" else None) if manifest.get("artifact_creation", True) else []
                with Session() as db:
                    old = {a.candidate_path: a for a in db.query(Artifact).filter_by(run_id=run_id)}
                if any(a.candidate_path in old and a.sha256 != old[a.candidate_path].sha256 for a in artifacts):
                    raise ValueError("OUTPUT_CHANGED_DURING_FINALIZATION")
                if spec and status == "COMPLETED":
                    report, slots = contract(spec, artifacts)
                    if not report["valid"]:
                        status = "FAILED"
                        error = {"code": "OUTPUT_CONTRACT_FAILED", "report": report}
                        for a in artifacts:
                            a.partial = True
            except (OSError, ValueError) as exc:
                artifacts, artifact_error, status = [], error_text(exc), "FAILED"
            with Session() as db:
                run = db.get(Run, run_id)
                run.manifest = encode(manifest)
                for artifact in artifacts:
                    if not db.get(Artifact, artifact.id):
                        db.add(artifact)
                        db.flush()
                        add_event(db, run_id, "FILE_CHANGED", {"path": artifact.candidate_path, "artifact_id": artifact.id,
                                  "sha256": artifact.sha256, "size": artifact.size, "origin": "filesystem_scan"})
                        add_event(db, run_id, "ARTIFACT_CREATED", {"artifact_id": artifact.id, "path": artifact.candidate_path,
                                  "sha256": artifact.sha256,
                                  "output_key": next((k for k, a in slots.items() if a.id == artifact.id), None)}, dedupe_key=f"{artifact.id}:created")
                run.status, run.phase, run.completed_at, run.safety_block = status, status, now(), False
                run.artifact_state = "ERROR" if artifact_error else "READY"
                if artifact_error:
                    error = {"code": "ARTIFACT_ERROR", "message": artifact_error}
                run.error = encode(error) if error else None
                if status == "CANCELLED" and not run.cancel_reason:
                    run.cancel_reason = "runtime_interruption"
                kind = f"RUN_{status}"
                if not db.query(Event).filter_by(run_id=run_id, type=kind).first():
                    add_event(db, run_id, kind, {"status": status, "artifact_count": len(artifacts), "error": run.error})
                task = db.query(TaskRun).filter_by(run_id=run_id).first()
                if task:
                    task.contract_report = encode(report) if report else None
                    settle(db, task, run, slots=slots if status == "COMPLETED" else None)
                from .conversation import finish_conversation
                finish_conversation(db, run)
                db.commit()
        self.wake.set()

        # Research/planning are ordinary Runs. Their terminal records advance a
        # FlowPlan through the existing queue without introducing another worker.
        try:
            from .flow_plans_api import on_run_finished
            on_run_finished(self, run_id)
        except Exception:
            logging.exception("Could not advance FlowPlan after Run %s", run_id)

    @staticmethod
    def final_message(turn):
        return turn.get("final_text", "")
