"""Connect Task attempts to Phase 1 Runs and finalize validated outputs."""
import json
from fastapi import HTTPException
from .db import Artifact, ArtifactRelation, Request, Run, Source, TaskRun, TaskRunOutput, Work
from .workflow import encode, outputs, task_event
from .run_service import create_run
from .artifact_service import admit_artifact, input_relation, artifact_edge
from .workspace import now


def task_spec(wr, task):
    spec = next((t for t in json.loads(wr.definition_snapshot)["tasks"] if t["id"] == task.task_definition_id), None)
    if spec is None:
        raise ValueError("Task is missing from the frozen Workflow snapshot: " + task.task_definition_id)
    spec.update(json.loads(task.execution_override or "{}"))
    return spec


def enqueue(db, wr, task, current):
    from .workflow_operations import gate, worker_profile
    if wr.paused or wr.cancel_requested:
        return
    spec = task_spec(wr, task)
    if any(current[p].status != "COMPLETED" or gate(db, current[p]) != "APPROVED" for p in spec["depends_on"]):
        return
    try:
        worker_profile(spec.get("execution_profile") or {})
    except Exception as exc:
        task.status, task.completed_at = "FAILED", now()
        task.error = encode({"code":"WORKER_PERMISSION_UNSAFE", "message":str(exc)})
        task_event(db, task, "TASK_FAILED", {"error":task.error})
        return
    changed = db.query(TaskRun).filter_by(id=task.id, status="READY").update({TaskRun.status: "QUEUED"}, synchronize_session=False)
    if not changed:
        return
    db.refresh(task)
    spec = task_spec(wr, task)
    snap = json.loads(wr.definition_snapshot)
    context = spec["context_rule"]
    selected = snap.get("workflow_context", {}) if context.get("inherit_workflow_context", True) else {}
    source_ids = list(dict.fromkeys(context.get("source_ids", []) + selected.get("source_ids", [])))
    artifact_ids = list(dict.fromkeys(context.get("artifact_ids", []) + selected.get("artifact_ids", [])))
    parent_task = db.get(TaskRun, task.parent_task_run_id) if task.parent_task_run_id else None
    parent = db.get(Run, parent_task.run_id) if parent_task and parent_task.run_id else None
    request = db.get(Request, parent.request_id) if parent and task.operation == "retry" else None
    context_config = {"strategy": "FORK_THREAD", "fork_thread_id": spec["fork_thread_id"], "fork_turn_id": spec["fork_turn_id"]} if spec.get("history_mode") == "FORK" else None
    try:
        with db.begin_nested():
            run = create_run(db, wr.work_id, spec["instruction"], source_ids, artifact_ids, spec["model"], spec["reasoning"],
                             operation=task.operation if task.operation in {"retry", "branch", "revision", "delayed_resume"} else "new",
                             parent=parent, request=request, frozen_workspace=snap.get("workspace_path"),
                             execution_profile=spec.get("execution_profile"), context_config=context_config)
    except (ValueError, OSError, HTTPException) as exc:
        task.status, task.completed_at = "FAILED", now()
        task.error = encode({"code": "CONTEXT_SELECTION_FAILED", "message": str(getattr(exc, "detail", exc))})
        task_event(db, task, "TASK_FAILED", {"error": task.error})
        return
    task.run_id = run.id
    db.flush()
    try:
        work = db.get(Work, wr.work_id)
        frozen = {r.input_key: r for r in db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=task.id)}
        rules = spec["input_rule"] + [{"input_key": f"context:{a}", "artifact_id": a} for a in artifact_ids]
        # A failed enqueue may have persisted only a prefix of bindings. Reuse those
        # exact IDs, but still resolve and validate EVERY declared input on Retry.
        for binding in rules:
            old = frozen.get(binding["input_key"])
            aid = old.source_artifact_id if old else binding.get("artifact_id")
            if not aid:
                source = current[binding["task_definition_id"]]
                output = db.get(TaskRunOutput, (source.id, binding["output_key"]))
                if source.status != "COMPLETED" or not output:
                    raise ValueError("Required Task output has not been confirmed")
                aid = output.artifact_id
            artifact = admit_artifact(db, aid, work, frozen=bool(old))
            expected = old.expected_sha256 if old else snap.get("artifact_hashes", {}).get(aid)
            if expected and artifact.sha256 != expected:
                raise ValueError("INPUT_ARTIFACT_CHANGED: " + aid)
            input_relation(db, task, binding["input_key"], artifact)
        task_event(db, task, "TASK_QUEUED")
    except ValueError as exc:
        run.status, run.phase, run.completed_at = "FAILED", "FAILED", now()
        run.error = encode({"code": "INPUT_BINDING_FAILED", "message": str(exc)})
        settle(db, task, run)
        from .conversation import finish_conversation
        finish_conversation(db, run)
        from .db import add_event
        add_event(db, run.id, "RUN_FAILED", {"error": run.error}, dedupe_key=f"{run.id}:failed")


def contract(spec, artifacts):
    by_path = {a.candidate_path: a for a in artifacts}
    errors, slots = [], {}
    for rule in outputs(spec):
        a = by_path.get(rule["path"])
        if not a:
            if rule["required"]:
                errors.append({"output_key": rule["output_key"], "code": "MISSING", "path": rule["path"]})
            continue
        if a.size == 0 and not rule.get("system"):
            errors.append({"output_key": rule["output_key"], "code": "EMPTY"})
        elif rule.get("media_type") and rule["media_type"] != a.content_type:
            errors.append({"output_key": rule["output_key"], "code": "MEDIA_TYPE"})
        else:
            slots[rule["output_key"]] = a
    return {"valid": not errors, "errors": errors,
            "outputs": [{"output_key": k, "artifact_id": a.id, "sha256": a.sha256, "path": a.relative_path} for k, a in slots.items()]}, slots


def settle(db, task, run, *, slots=None):
    previous = task.status
    previous_error = task.error
    task.status, task.error, task.completed_at = run.status, run.error, run.completed_at
    task.blocked_reason = None
    if slots and run.status == "COMPLETED":
        inputs = db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=task.id).all()
        for key, artifact in slots.items():
            if not db.get(TaskRunOutput, (task.id, key)):
                db.add(TaskRunOutput(task_run_id=task.id, output_key=key, artifact_id=artifact.id))
            for binding in inputs:
                artifact_edge(db, "DERIVED_FROM", binding.source_artifact_id, artifact.id)
        from .db import WorkflowRun
        spec = task_spec(db.get(WorkflowRun, task.workflow_run_id), task)
        for key, original in spec.get("revision_of", {}).items():
            if key in slots:
                artifact_edge(db, "REVISION_OF", original, slots[key].id)
    if run.status == "COMPLETED":
        from .workflow_operations import ensure_review
        ensure_review(db, task, list((slots or {}).values()))
    if previous == "FAILED" and run.status != "FAILED":
        task_event(db, task, "TASK_RECONCILED", {"previous_error": previous_error, "error": run.error,
                                               "runtime_status": run.runtime_status}, suffix=run.status)
    task_event(db, task, f"TASK_{task.status}", {"error": run.error})
