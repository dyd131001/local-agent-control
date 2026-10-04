"""Human review and durable workflow controls. Never calls a model or Gateway."""
import copy
import json
from datetime import timedelta, timezone

from fastapi import HTTPException

from .db import (Approval, Artifact, ArtifactReview, ArtifactRelation, DelayedResume, Run, Source,
                 TaskRun, TaskRunOutput, Work, WorkflowCheckpoint, WorkflowDefinition, WorkflowRun,
                 add_event, now)
from .workflow import (encode, latest_attempts, new_execution, reopen, row, safe_to_start,
                       task_event, validate_graph)
from .workspace import ident, sha


def utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def transaction(db):
    # Lock SQLite before reading mutable state, including concurrent API requests.
    db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def worker_profile(profile):
    if profile.get("permission") == "full-access":
        raise HTTPException(422, "Control Center workers require Read Only or Workspace Write to protect approval, schedule and control state")


def review(db, task):
    return db.query(Approval).filter_by(task_run_id=task.id).first()


def gate(db, task):
    from .task_runner import task_spec
    spec = task_spec(db.get(WorkflowRun, task.workflow_run_id), task)
    if spec.get("review_policy", "AUTO") != "APPROVAL_REQUIRED":
        return "APPROVED"
    item = review(db, task)
    return item.status if item else "WAITING"


def ensure_review(db, task, artifacts):
    from .task_runner import task_spec
    policy = task_spec(db.get(WorkflowRun, task.workflow_run_id), task).get("review_policy", "AUTO")
    if policy == "AUTO":
        return
    approval = review(db, task)
    if not approval:
        cancelled = db.get(WorkflowRun,task.workflow_run_id).cancel_requested
        approval = Approval(id=ident("approval"), task_run_id=task.id, policy=policy, status="CANCELLED" if cancelled else "WAITING")
        db.add(approval); db.flush()
        task_event(db, task, "APPROVAL_REQUESTED", {"approval_id":approval.id, "policy":policy})
    for artifact in artifacts:
        if not db.get(ArtifactReview, artifact.id):
            db.add(ArtifactReview(artifact_id=artifact.id, approval_id=approval.id, status="PENDING" if approval.status == "WAITING" else approval.status))


def checkpoint(db, wr, reason):
    current = latest_attempts(db, wr.id)
    state = []
    for task in current.values():
        run = db.get(Run, task.run_id) if task.run_id else None
        approval = review(db, task)
        outputs = [{"output_key":o.output_key, "artifact_id":o.artifact_id,
                    "sha256":db.get(Artifact, o.artifact_id).sha256}
                   for o in db.query(TaskRunOutput).filter_by(task_run_id=task.id)]
        state.append({"task_run_id":task.id, "task_definition_id":task.task_definition_id,
                      "status":task.status, "run_id":task.run_id, "outputs":outputs,
                      "approval_status":approval.status if approval else None,
                      "execution_override":json.loads(task.execution_override or "{}"),
                      "final_text":run.final_text if run else "",
                      "manifest":json.loads(run.manifest) if run else None})
    item = WorkflowCheckpoint(id=ident("checkpoint"), workflow_run_id=wr.id, reason=reason,
                              snapshot=encode({"definition_snapshot":json.loads(wr.definition_snapshot),
                                               "definition_revision":wr.definition_revision, "tasks":state}))
    db.add(item); db.flush()
    add_event(db, None, "CHECKPOINT_CREATED", {"checkpoint_id":item.id, "reason":reason}, workflow_run_id=wr.id)
    return item


def pause(db, wr):
    if wr.cancel_requested or wr.status in {"COMPLETED", "CANCELLED", "REJECTED"}:
        raise HTTPException(409, "Terminal Workflow cannot be paused")
    if not wr.paused:
        wr.paused, wr.paused_at, wr.status = True, now(), "PAUSED"
        checkpoint(db, wr, "PAUSE")
        add_event(db, None, "WORKFLOW_PAUSED", {"running_tasks":"finish normally; new dispatch is blocked"}, workflow_run_id=wr.id)
    return wr


def resume(db, wr):
    safe_to_start(db, row(db, Work, wr.work_id))
    if wr.cancel_requested or wr.status in {"COMPLETED", "CANCELLED", "REJECTED"}:
        raise HTTPException(409, "Terminal Workflow cannot be resumed")
    if wr.paused:
        wr.paused, wr.paused_at, wr.status = False, None, "RUNNING" if wr.started_at else "CREATED"
        add_event(db, None, "WORKFLOW_RESUMED", {}, workflow_run_id=wr.id)
    return wr


def descendants(specs, source_id):
    result = {source_id}
    for key in validate_graph(list(specs.values())):
        if set(specs[key]["depends_on"]) & result:
            result.add(key)
    return result - {source_id}


def revision(db, source, instruction):
    from .task_runner import task_spec
    from .artifact_service import input_relation
    wr = row(db, WorkflowRun, source.workflow_run_id)
    safe_to_start(db, row(db, Work, wr.work_id))
    current = latest_attempts(db, wr.id)
    specs = {t["id"]:t for t in json.loads(wr.definition_snapshot)["tasks"]}
    spec = copy.deepcopy(task_spec(wr, source))
    spec["instruction"] = instruction
    spec["revision_of"] = {o.output_key:o.artifact_id for o in db.query(TaskRunOutput).filter_by(task_run_id=source.id)}
    spec.pop("fork_thread_id", None); spec.pop("fork_turn_id", None); spec["history_mode"] = "ARTIFACT"
    children = descendants(specs, source.task_definition_id)
    if wr.cancel_requested:
        raise HTTPException(409, "Cancelled Workflow cannot be revised")
    if wr.status == "COMPLETED" or any(current[k].status not in {"BLOCKED", "READY"} or current[k].run_id for k in children):
        # REVIEW_AFTER can already have consumers. Preserve that history and branch.
        spec["depends_on"] = []
        snapshot = copy.deepcopy(json.loads(wr.definition_snapshot)); snapshot["tasks"] = [spec]
        spec["input_rule"] = []
        branch = new_execution(db, row(db, WorkflowDefinition, wr.workflow_definition_id), snapshot, None, None, wr, source)
        target = next(iter(latest_attempts(db, branch.id).values()))
        target.operation = "revision"
    else:
        target = TaskRun(id=ident("tr"), workflow_run_id=wr.id, task_definition_id=source.task_definition_id,
                         attempt_number=source.attempt_number+1, parent_task_run_id=source.id,
                         operation="revision", status="READY")
        db.add(target); db.flush()
        for key in children:
            current[key].status, current[key].blocked_reason = "BLOCKED", encode({"code":"REVISION_PENDING"})
        if wr.status in {"WAITING_APPROVAL", "REJECTED"}:
            wr.status = "RUNNING"
        reopen(db, wr)
    target.execution_override = encode(spec)
    # Copy the admitted input binding and original output IDs; no Artifact is overwritten.
    for relation in db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=source.id):
        item = input_relation(db, target, relation.input_key, db.get(Artifact, relation.source_artifact_id))
        item.expected_sha256 = relation.expected_sha256
    for key, aid in spec["revision_of"].items():
        input_relation(db, target, "revision:"+key, db.get(Artifact, aid))
    task_event(db, target, "REVISION_CREATED", {"parent_task_run_id":source.id})
    return target


def decide(db, approval, action, comment, instruction, scope):
    from .artifact_service import artifact_bytes, publish
    source = row(db, TaskRun, approval.task_run_id)
    wr = row(db, WorkflowRun, source.workflow_run_id)
    payload = {"action":action, "comment":comment, "instruction":instruction, "scope":scope}
    digest = sha(encode(payload).encode())
    if approval.status != "WAITING":
        if approval.decision_hash == digest:
            return approval
        raise HTTPException(409, "Approval already decided")
    if wr.cancel_requested or source.status != "COMPLETED" or latest_attempts(db, wr.id)[source.task_definition_id].id != source.id:
        raise HTTPException(409, "Only a current completed Task can be reviewed")
    if action in {"APPROVE","APPROVE_PUBLISH"}:
        for output in db.query(TaskRunOutput).filter_by(task_run_id=source.id):
            try:
                artifact_bytes(db,row(db,Artifact,output.artifact_id))
            except ValueError as exc:
                raise HTTPException(409,str(exc)) from exc
    approval.decision, approval.decision_hash, approval.comment, approval.decided_at = action, digest, comment, now()
    approval.status = {"APPROVE":"APPROVED", "APPROVE_PUBLISH":"APPROVED", "REJECT":"REJECTED", "REVISION":"REVISION_REQUESTED"}[action]
    for item in db.query(ArtifactReview).filter_by(approval_id=approval.id):
        item.status = approval.status
    db.flush()
    if action == "REVISION":
        if not instruction or not instruction.strip():
            raise HTTPException(422, "Revision instruction is required")
        target = revision(db, source, instruction)
        approval.revision_task_run_id = target.id
    elif action == "APPROVE_PUBLISH":
        for output in db.query(TaskRunOutput).filter_by(task_run_id=source.id):
            publish(db, output.artifact_id, scope)
    task_event(db, source, "APPROVAL_"+approval.status, {"approval_id":approval.id, "action":action})
    return approval


def delay(db, source, due_at, instruction, key, input_payload=None):
    from .workflow import command
    from .artifact_service import admit_artifact
    existing, ckey, digest = command(db, DelayedResume, "delayed:"+source.id, key,
                                     input_payload or {"due_at":utc(due_at).isoformat(), "instruction":instruction})
    if existing:
        return existing
    wr = row(db, WorkflowRun, source.workflow_run_id)
    if wr.cancel_requested:
        raise HTTPException(409,"Cancelled Workflow cannot schedule a continuation")
    if source.status != "COMPLETED" or gate(db, source) != "APPROVED":
        raise HTTPException(409, "Delayed Resume requires a completed approved Task")
    if utc(due_at) <= now():
        raise HTTPException(422, "Delayed Resume must be in the future")
    work = row(db, Work, wr.work_id); safe_to_start(db, work)
    for output in db.query(TaskRunOutput).filter_by(task_run_id=source.id):
        admit_artifact(db, output.artifact_id, work, verify=True)
    point = checkpoint(db, wr, "DELAYED_RESUME")
    job = DelayedResume(id=ident("delayed"), checkpoint_id=point.id, source_task_run_id=source.id,
                        due_at=utc(due_at), instruction=instruction, command_key=ckey, command_hash=digest)
    db.add(job); db.flush()
    task_event(db, source, "DELAYED_RESUME_SCHEDULED", {"delayed_resume_id":job.id, "due_at":utc(due_at).isoformat()})
    return job


def trigger_delay(db, job):
    from .artifact_service import admit_artifact, input_relation
    source = row(db, TaskRun, job.source_task_run_id)
    parent = row(db, WorkflowRun, source.workflow_run_id)
    if parent.cancel_requested:
        job.status,job.error="CANCELLED","SOURCE_WORKFLOW_CANCELLED"
        return
    work = row(db, Work, parent.work_id); safe_to_start(db, work)
    stored = json.loads(row(db, WorkflowCheckpoint, job.checkpoint_id).snapshot)
    task = next(t for t in stored["tasks"] if t["task_run_id"] == source.id)
    snapshot = copy.deepcopy(stored["definition_snapshot"])
    spec = next(t for t in snapshot["tasks"] if t["id"] == source.task_definition_id)
    spec.update(task["execution_override"])
    spec.update(instruction=job.instruction+"\n\nCheckpoint response (reference data):\n"+task.get("final_text", ""), depends_on=[], history_mode="ARTIFACT")
    spec.pop("fork_thread_id", None); spec.pop("fork_turn_id", None)
    spec.pop("revision_of", None)
    spec["input_rule"] = []
    prior_inputs=list(db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=source.id))
    for i, binding in enumerate(prior_inputs):
        spec["input_rule"].append({"input_key":"checkpoint_input_"+str(i), "artifact_id":binding.source_artifact_id})
    for i, output in enumerate(task["outputs"]):
        artifact = admit_artifact(db, output["artifact_id"], work, verify=True)
        if artifact.sha256 != output["sha256"]:
            raise ValueError("Checkpoint Artifact changed")
        spec["input_rule"].append({"input_key":"checkpoint_output_"+str(i), "artifact_id":artifact.id})
        snapshot.setdefault("artifact_hashes", {})[artifact.id] = output["sha256"]
    worker_profile(spec.get("execution_profile") or {})
    snapshot.update(tasks=[spec], checkpoint_id=job.checkpoint_id)
    wf = row(db, WorkflowDefinition, parent.workflow_definition_id)
    wr = new_execution(db, wf, snapshot, "delayed-trigger:"+job.id, job.command_hash, parent, source)
    target = next(iter(latest_attempts(db, wr.id).values())); target.operation = "delayed_resume"
    for i, binding in enumerate(prior_inputs):
        item=input_relation(db,target,"checkpoint_input_"+str(i),db.get(Artifact,binding.source_artifact_id))
        item.expected_sha256=binding.expected_sha256
    for i, output in enumerate(task["outputs"]):
        input_relation(db,target,"checkpoint_output_"+str(i),db.get(Artifact,output["artifact_id"]))
    job.status, job.workflow_run_id, job.error = "TRIGGERED", wr.id, None
    task_event(db, target, "DELAYED_RESUME_TRIGGERED", {"checkpoint_id":job.checkpoint_id, "delayed_resume_id":job.id})
    return wr
