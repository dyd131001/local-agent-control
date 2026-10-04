"""Deterministic DAG scheduling; no AI or Runtime decisions."""
import json
from .db import Run, Session, TaskRun, WorkflowRun, add_event, now
from .workflow import COMMAND_LOCK, encode, latest_attempts, reopen, task_event, validate_graph
from .task_runner import enqueue, settle, task_spec
from .workflow_operations import gate


def aggregate(db, wr, current):
    statuses = [t.status for t in current.values()]
    if wr.paused and not wr.cancel_requested:
        wr.status = "PAUSED"
        return
    if any(s in {"READY", "QUEUED", "RUNNING"} for s in statuses):
        return
    unknown = any(t.run_id and db.get(Run, t.run_id).safety_block for t in current.values())
    if wr.cancel_requested and not unknown:
        status = "CANCELLED"
    elif any(t.status == "COMPLETED" and gate(db, t) in {"REJECTED", "CANCELLED"} for t in current.values()):
        status = "REJECTED"
    elif any(t.status == "COMPLETED" and gate(db, t) != "APPROVED" for t in current.values()):
        status = "WAITING_APPROVAL"
    elif all(s == "COMPLETED" for s in statuses):
        status = "COMPLETED"
    else:
        status = "PARTIAL" if "COMPLETED" in statuses else "FAILED"
    if wr.status == status:
        return
    wr.status, wr.completed_at = status, None if status == "WAITING_APPROVAL" else now()
    wr.error = None if status in {"COMPLETED", "WAITING_APPROVAL"} else encode({"code": "WORKFLOW_INCOMPLETE", "tasks": {k: t.status for k, t in current.items() if t.status != "COMPLETED"}})
    add_event(db, None, f"WORKFLOW_{status}", {"status": status, "error": wr.error, "execution_round": wr.execution_round},
              workflow_run_id=wr.id, dedupe_key=f"{wr.id}:{status}:{wr.execution_round}")


def start_workflow(db, task):
    wr = db.get(WorkflowRun, task.workflow_run_id)
    if wr.status == "CREATED":
        wr.status, wr.started_at = "RUNNING", now()
        add_event(db, None, "WORKFLOW_STARTED", {"execution_round": wr.execution_round},
                  workflow_run_id=wr.id, dedupe_key=f"{wr.id}:started:{wr.execution_round}")


def tick():
    with COMMAND_LOCK, Session() as db:
        workflows = db.query(WorkflowRun).filter(WorkflowRun.status.in_(["CREATED", "RUNNING", "FAILED", "PARTIAL", "WAITING_APPROVAL", "PAUSED", "REJECTED"])).all()
        blocked = bool(db.query(Run.id).filter_by(safety_block=True).first())
        for wr in workflows:
            current = latest_attempts(db, wr.id)
            snapshot = json.loads(wr.definition_snapshot)
            specs = {key:task_spec(wr, task) for key, task in current.items()}
            for task in current.values():
                if task.run_id and task.status in {"QUEUED", "RUNNING"}:
                    run = db.get(Run, task.run_id)
                    # Successful Task completion MUST come from the Contract
                    # finalizer. A standalone Run terminal is not sufficient proof.
                    if run.status in {"FAILED", "CANCELLED"}:
                        settle(db, task, run)
            for key in validate_graph(snapshot["tasks"]):
                task, spec = current[key], specs[key]
                if task.status not in {"BLOCKED", "READY"}:
                    continue
                parents = [current[p] for p in spec["depends_on"]]
                if any(p.status in {"CANCELLED", "SKIPPED"} or gate(db, p) in {"REJECTED", "CANCELLED"} for p in parents):
                    task.status, task.completed_at = "SKIPPED", now()
                    task.blocked_reason = encode({"code": "DEPENDENCY_ABANDONED"})
                    task_event(db, task, "TASK_SKIPPED")
                elif all(p.status == "COMPLETED" and gate(db, p) == "APPROVED" for p in parents):
                    if task.status == "READY":
                        continue
                    task.status, task.blocked_reason = "READY", None
                    if wr.status == "WAITING_APPROVAL" and not wr.paused:
                        wr.status = "RUNNING"
                    reopen(db, wr)
                    task_event(db, task, "TASK_READY")
                else:
                    task.status = "BLOCKED"
                    reason = {"code": "WAITING_APPROVAL" if any(p.status == "COMPLETED" and gate(db,p) != "APPROVED" for p in parents) else "DEPENDENCY_FAILED" if any(p.status == "FAILED" for p in parents) else "DEPENDENCY_PENDING",
                              "task_run_ids": [p.id for p in parents if p.status != "COMPLETED" or gate(db,p) != "APPROVED"]}
                    if task.blocked_reason != encode(reason):
                        task.blocked_reason = encode(reason)
                        task_event(db, task, "TASK_BLOCKED", reason, suffix=encode(reason))
            if not wr.paused and not wr.cancel_requested and not blocked:
                for key in validate_graph(snapshot["tasks"]):
                    if current[key].status == "READY":
                        enqueue(db, wr, current[key], current)
            aggregate(db, wr, current)
        db.commit()


def cancel_task(db, task, *, workflow_cancel=False):
    if task.status == "FAILED" and not workflow_cancel:
        wr = db.get(WorkflowRun, task.workflow_run_id)
        if task.run_id and db.get(Run, task.run_id).safety_block:
            from fastapi import HTTPException
            raise HTTPException(409, "Reconcile unknown outcome before abandoning")
        current = latest_attempts(db, wr.id)
        descendants = {task.task_definition_id}
        specs = {t["id"]: t for t in json.loads(wr.definition_snapshot)["tasks"]}
        for key in validate_graph(list(specs.values())):
            if set(specs[key]["depends_on"]) & descendants:
                descendants.add(key)
                child = current[key]
                if child.status == "BLOCKED":
                    child.status, child.completed_at = "SKIPPED", now()
                    child.blocked_reason = encode({"code": "DEPENDENCY_ABANDONED", "task_run_id": task.id})
                    task_event(db, child, "TASK_SKIPPED")
        return None
    if task.status not in {"BLOCKED", "READY", "QUEUED", "RUNNING"}:
        return None
    task.cancel_requested = True
    if not task.run_id:
        task.status, task.completed_at = "CANCELLED", now()
        task_event(db, task, "TASK_CANCELLED")
        return None
    run = db.get(Run, task.run_id)
    run.cancel_requested, run.cancel_reason = True, "user_cancel"
    if run.phase == "QUEUED":
        run.status, run.phase, run.completed_at = "CANCELLED", "CANCELLED", now()
        add_event(db, run.id, "RUN_CANCELLED", {"reason": "cancelled before dispatch"}, dedupe_key=f"{run.id}:cancelled")
        settle(db, task, run)
        from .conversation import finish_conversation
        finish_conversation(db, run)
    elif run.status == "RUNNING":
        run.phase = "CANCEL_REQUESTED"
    return run.id
