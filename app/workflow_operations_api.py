"""Small, guarded APIs for human operations above the Workflow Engine."""
import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request as HttpRequest
from pydantic import Field, model_validator

from .db import (Approval, Artifact, ArtifactPublication, ArtifactReview, DelayedResume, Run,
                 ScheduleFire, Session, TaskRun, TaskRunOutput, Work, WorkflowCheckpoint,
                 WorkflowDefinition, WorkflowRun, WorkflowSchedule, dump, now, read_snapshot)
from .workflow import COMMAND_LOCK, StrictBody, definition, row, safe_to_start, validate_context
from .workflow_operations import checkpoint, decide, delay, pause, resume, transaction, utc
from .workspace import ident

router = APIRouter(prefix="/api")
runner = None


def configure(shared_runner):
    global runner
    runner = shared_runner
    return router


def approval_detail(db, item):
    task = row(db, TaskRun, item.task_run_id)
    wr = row(db, WorkflowRun, task.workflow_run_id)
    outputs = []
    for output in db.query(TaskRunOutput).filter_by(task_run_id=task.id):
        artifact = row(db, Artifact, output.artifact_id)
        reviewed = db.get(ArtifactReview, artifact.id)
        published = db.query(ArtifactPublication).filter_by(artifact_id=artifact.id).first()
        outputs.append({"output_key":output.output_key, "artifact":dump(artifact),
                        "review_status":reviewed.status if reviewed else None,
                        "publication":dump(published) if published else None})
    return {**dump(item), "workflow_run_id":wr.id, "work_id":wr.work_id,
            "revision_workflow_run_id":db.get(TaskRun,item.revision_task_run_id).workflow_run_id if item.revision_task_run_id else None,
            "task_definition_id":task.task_definition_id, "task_status":task.status,
            "final_text":db.get(Run,task.run_id).final_text if task.run_id else "", "outputs":outputs}


@router.get("/approvals")
def inbox(work_id: str | None = None, status: Literal["WAITING","APPROVED","REJECTED","REVISION_REQUESTED","CANCELLED"] = "WAITING"):
    with Session() as db:
        read_snapshot(db)
        query = db.query(Approval).join(TaskRun, Approval.task_run_id == TaskRun.id).join(WorkflowRun, TaskRun.workflow_run_id == WorkflowRun.id).filter(Approval.status == status)
        if work_id:
            query = query.filter(WorkflowRun.work_id == work_id)
        return [approval_detail(db,item) for item in query.order_by(Approval.created_at,Approval.id).limit(200)]


class DecisionBody(StrictBody):
    action: Literal["APPROVE","APPROVE_PUBLISH","REJECT","REVISION"]
    comment: str = Field(default="",max_length=10000)
    instruction: str | None = Field(default=None,max_length=30000)
    scope: Literal["WORK","CATEGORY","GLOBAL"] = "WORK"


@router.post("/approvals/{approval_id}/decision")
def decision(approval_id: str, body: DecisionBody):
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        item=decide(db,row(db,Approval,approval_id),body.action,body.comment,body.instruction,body.scope)
        db.commit()
        result=approval_detail(db,item)
        if body.action == "APPROVE_PUBLISH":
            from .storage import remove_published_staging
            for output in result["outputs"]:
                remove_published_staging(db.get(Artifact,output["artifact"]["id"]))
    runner.wake.set()
    return result


@router.post("/workflow-runs/{workflow_run_id}/pause")
def pause_execution(workflow_run_id: str):
    with COMMAND_LOCK, Session() as db:
        transaction(db); item=pause(db,row(db,WorkflowRun,workflow_run_id)); db.commit()
        runner.wake.set(); return dump(item)


@router.post("/workflow-runs/{workflow_run_id}/resume")
def resume_execution(workflow_run_id: str):
    with COMMAND_LOCK, Session() as db:
        transaction(db); item=resume(db,row(db,WorkflowRun,workflow_run_id)); db.commit()
        runner.wake.set(); return dump(item)


@router.get("/workflow-runs/{workflow_run_id}/checkpoints")
def checkpoints(workflow_run_id: str):
    with Session() as db:
        row(db,WorkflowRun,workflow_run_id)
        return [{**dump(c),"snapshot":json.loads(c.snapshot)} for c in db.query(WorkflowCheckpoint).filter_by(workflow_run_id=workflow_run_id).order_by(WorkflowCheckpoint.created_at.desc()).limit(50)]


class ScheduleBody(StrictBody):
    kind: Literal["ONE_TIME","RECURRING"]
    start_at: datetime
    interval_minutes: int | None = Field(default=None,ge=1,le=525600)
    enabled: bool = True
    misfire_policy: Literal["FIRE_ONCE","SKIP"] = "FIRE_ONCE"
    grace_seconds: int = Field(default=300,ge=0,le=86400)
    source_ids: list[str] = Field(default_factory=list,max_length=100)
    artifact_ids: list[str] = Field(default_factory=list,max_length=100)

    @model_validator(mode="after")
    def valid(self):
        if not self.start_at.tzinfo or utc(self.start_at) <= now():
            raise ValueError("Schedule start must be a future time with timezone")
        if self.kind == "RECURRING" and self.interval_minutes is None:
            raise ValueError("Recurring schedule requires an interval")
        if self.kind == "ONE_TIME" and self.interval_minutes is not None:
            raise ValueError("One-time schedule has no interval")
        if len(self.source_ids) != len(set(self.source_ids)) or len(self.artifact_ids) != len(set(self.artifact_ids)):
            raise ValueError("Duplicate context selection")
        return self


@router.post("/workflows/{workflow_id}/schedules",status_code=201)
def create_schedule(workflow_id: str,body: ScheduleBody):
    with COMMAND_LOCK,Session() as db:
        transaction(db)
        wf=row(db,WorkflowDefinition,workflow_id); work=row(db,Work,wf.work_id); safe_to_start(db,work)
        if not wf.enabled or json.loads(wf.unresolved_bindings):
            raise HTTPException(409,"Workflow must be enabled and bindings resolved")
        validate_context(db,work,definition(db,wf.id)["tasks"],body.source_ids,body.artifact_ids)
        item=WorkflowSchedule(id=ident("schedule"),workflow_definition_id=wf.id,kind=body.kind,enabled=body.enabled,
            interval_seconds=body.interval_minutes*60 if body.interval_minutes else None,next_fire_at=utc(body.start_at),
            context=json.dumps({"source_ids":body.source_ids,"artifact_ids":body.artifact_ids}),
            misfire_policy=body.misfire_policy,grace_seconds=body.grace_seconds)
        db.add(item);db.commit();runner.wake.set();return dump(item)


@router.get("/schedules")
def schedules(work_id: str | None = None):
    with Session() as db:
        query=db.query(WorkflowSchedule).join(WorkflowDefinition,WorkflowSchedule.workflow_definition_id==WorkflowDefinition.id)
        if work_id:
            query=query.filter(WorkflowDefinition.work_id==work_id)
        return [dump(s) for s in query.order_by(WorkflowSchedule.created_at.desc()).limit(200)]


@router.get("/schedules/{schedule_id}")
def schedule_detail(schedule_id: str):
    with Session() as db:
        read_snapshot(db)
        return {"schedule":dump(row(db,WorkflowSchedule,schedule_id)),"fires":[dump(f) for f in db.query(ScheduleFire).filter_by(schedule_id=schedule_id).order_by(ScheduleFire.scheduled_for.desc()).limit(100)]}


class ScheduleUpdate(StrictBody):
    enabled: bool
    next_fire_at: datetime | None = None
    kind: Literal["ONE_TIME", "RECURRING"] | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    misfire_policy: Literal["FIRE_ONCE", "SKIP"] | None = None
    grace_seconds: int | None = Field(default=None, ge=0, le=86400)
    source_ids: list[str] | None = Field(default=None, max_length=100)
    artifact_ids: list[str] | None = Field(default=None, max_length=100)


@router.patch("/schedules/{schedule_id}")
def schedule_update(schedule_id: str,body: ScheduleUpdate):
    with COMMAND_LOCK,Session() as db:
        transaction(db); item=row(db,WorkflowSchedule,schedule_id)
        if body.kind is not None:
            item.kind=body.kind
            if body.kind=="RECURRING":
                if body.interval_minutes is None and item.interval_seconds is None:
                    raise HTTPException(422,"반복 간격을 입력하세요.")
                if body.interval_minutes is not None:item.interval_seconds=body.interval_minutes*60
            else:item.interval_seconds=None
        elif body.interval_minutes is not None:
            if item.kind!="RECURRING":raise HTTPException(422,"한 번 실행 예약에는 반복 간격을 지정할 수 없습니다.")
            item.interval_seconds=body.interval_minutes*60
        if body.misfire_policy is not None:item.misfire_policy=body.misfire_policy
        if body.grace_seconds is not None:item.grace_seconds=body.grace_seconds
        if body.source_ids is not None or body.artifact_ids is not None:
            wf=row(db,WorkflowDefinition,item.workflow_definition_id);work=row(db,Work,wf.work_id)
            previous=json.loads(item.context)
            source_ids=body.source_ids if body.source_ids is not None else previous.get("source_ids",[])
            artifact_ids=body.artifact_ids if body.artifact_ids is not None else previous.get("artifact_ids",[])
            if len(source_ids)!=len(set(source_ids)) or len(artifact_ids)!=len(set(artifact_ids)):
                raise HTTPException(422,"중복 자료를 선택했습니다.")
            validate_context(db,work,definition(db,wf.id)["tasks"],source_ids,artifact_ids)
            item.context=json.dumps({"source_ids":source_ids,"artifact_ids":artifact_ids})
        if body.next_fire_at is not None:
            if not body.next_fire_at.tzinfo or utc(body.next_fire_at)<=now():
                raise HTTPException(422,"Next fire time must be in the future with timezone")
            item.next_fire_at=utc(body.next_fire_at)
        if body.enabled and item.next_fire_at is None:
            raise HTTPException(409,"Completed one-time schedule requires a new fire time")
        item.enabled=body.enabled
        if not item.enabled:
            for fire in db.query(ScheduleFire).filter_by(schedule_id=item.id,status="CLAIMED"):
                fire.status,fire.error="CANCELLED","SCHEDULE_DISABLED"
        db.commit();runner.wake.set();return dump(item)


class DelayBody(StrictBody):
    instruction: str = Field(min_length=1,max_length=30000)
    due_at: datetime | None = None
    delay_hours: float | None = Field(default=None,gt=0,le=8760)

    @model_validator(mode="after")
    def valid(self):
        if not self.instruction.strip() or (self.due_at is None)==(self.delay_hours is None):
            raise ValueError("Provide an instruction and either due_at or delay_hours")
        if self.due_at is not None and not self.due_at.tzinfo:
            raise ValueError("Resume time must include timezone")
        return self


@router.post("/task-runs/{task_run_id}/delayed-resumes",status_code=201)
def create_delay(task_run_id: str,body: DelayBody,http: HttpRequest):
    due=body.due_at or now()+timedelta(hours=body.delay_hours)
    with COMMAND_LOCK,Session() as db:
        transaction(db)
        item=delay(db,row(db,TaskRun,task_run_id),due,body.instruction,http.headers.get("idempotency-key"),body.model_dump(mode="json"))
        db.commit();runner.wake.set();return dump(item)


@router.get("/delayed-resumes")
def delays(work_id: str | None = None):
    with Session() as db:
        query=db.query(DelayedResume).join(TaskRun,DelayedResume.source_task_run_id==TaskRun.id).join(WorkflowRun,TaskRun.workflow_run_id==WorkflowRun.id)
        if work_id:
            query=query.filter(WorkflowRun.work_id==work_id)
        return [dump(d) for d in query.order_by(DelayedResume.due_at).limit(200)]


@router.post("/delayed-resumes/{delayed_resume_id}/cancel")
def cancel_delay(delayed_resume_id: str):
    with COMMAND_LOCK,Session() as db:
        transaction(db); item=row(db,DelayedResume,delayed_resume_id)
        if item.status not in {"PENDING","CANCELLED"}:
            raise HTTPException(409,"Delayed Resume already triggered")
        item.status="CANCELLED";db.commit();return dump(item)


def monitoring(db):
    return {"workflows":[dump(w) for w in db.query(WorkflowRun).filter(WorkflowRun.status.in_(["CREATED","RUNNING","WAITING_APPROVAL","PAUSED"])).order_by(WorkflowRun.created_at.desc()).limit(100)],
            "waiting_approvals":db.query(Approval).filter_by(status="WAITING").count(),
            "schedules":[dump(s) for s in db.query(WorkflowSchedule).filter_by(enabled=True).order_by(WorkflowSchedule.next_fire_at).limit(100)],
            "delayed_resumes":[dump(d) for d in db.query(DelayedResume).filter_by(status="PENDING").order_by(DelayedResume.due_at).limit(100)]}


@router.get("/workflow-monitoring")
def monitor():
    with Session() as db:
        read_snapshot(db);return monitoring(db)
