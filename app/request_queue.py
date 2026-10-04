"""Durable Request conditions handled by the existing time triggers and Run dispatcher."""
import json
from datetime import datetime
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, HTTPException, Request as HttpRequest
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import defer

from .context_policy import prompt_cost
from .conversation import freeze_context, row, snapshot
from .db import Category, Request, RequestQueue, Run, Session, ThreadRecord, Work, dump, now
from .execution_settings import ExecutionProfile, catalog_from, inherited, resolve
from .workflow import COMMAND_LOCK
from .workflow_operations import transaction, utc, worker_profile
from .workspace import ident, sha

router = APIRouter(prefix='/api')
runner = None
queue_run = None
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED'}


def configure(worker, enqueue):
    global runner, queue_run
    runner, queue_run = worker, enqueue
    return router


class QueueBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=30000)
    condition: Literal['NOW', 'AT_TIME', 'AFTER_RUN_COMPLETED', 'AFTER_RUN_SUCCEEDED']
    due_at: datetime | None = None
    predecessor_run_id: str | None = None
    context_ids: list[str] = Field(default_factory=list, max_length=100)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)
    exclude_resource_ids: list[str] = Field(default_factory=list, max_length=100)
    context_thread_id: str | None = None
    pack_id: str | None = None
    budget: int = Field(default=40000, ge=100, le=1000000)
    allow_over_budget: bool = False
    context_policies: dict[str, Literal['REFERENCE','RETRIEVE','FULL']] = Field(default_factory=dict, max_length=300)
    execution_profile: ExecutionProfile | None = None

    @field_validator('instruction')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('요청을 입력하세요')
        return value

    @model_validator(mode='after')
    def condition_fields(self):
        if self.condition == 'AT_TIME':
            if not self.due_at or not self.due_at.tzinfo:
                raise ValueError('시간대가 포함된 실행 시각이 필요합니다')
        elif self.due_at is not None:
            raise ValueError('특정 시각 예약에서만 실행 시각을 지정할 수 있습니다')
        if self.condition.startswith('AFTER_RUN_'):
            if not self.predecessor_run_id:
                raise ValueError('선행 Run을 선택하세요')
        elif self.predecessor_run_id:
            raise ValueError('후속 실행에서만 선행 Run을 지정할 수 있습니다')
        return self


def available_work(db, work):
    if work.archived or work.provision_state != 'READY' or not row(db, Category, work.category_id).active:
        raise HTTPException(409, '활성 Category / Work에서만 요청을 실행할 수 있습니다')


def view(db, job):
    request = row(db, Request, job.request_id)
    result = dump(job)
    result.update(instruction=request.instruction, context_ids=json.loads(request.context_ids),
                  artifact_ids=json.loads(request.artifact_ids), queue_status=job.status)
    if job.run_id:
        run = row(db, Run, job.run_id)
        result['status'] = 'QUEUED' if run.status == 'CREATED' else run.status
        result['run_phase'] = run.phase
    if job.predecessor_run_id:
        parent = row(db, Run, job.predecessor_run_id)
        result['predecessor'] = {'status': parent.status,
            'instruction': row(db, Request, parent.request_id).instruction[:160]}
    return result


@router.get('/works/{work_id}/request-queue')
def list_queue(work_id: str):
    with Session() as db:
        row(db, Work, work_id)
        return [view(db, job) for job in db.query(RequestQueue).filter_by(work_id=work_id)
                .order_by(RequestQueue.created_at, RequestQueue.id)]


@router.post('/works/{work_id}/request-queue', status_code=202)
async def register(work_id: str, body: QueueBody, http: HttpRequest):
    catalog = await catalog_from(runner.gateway)
    fingerprint = sha(json.dumps(body.model_dump(mode='json'), sort_keys=True).encode())
    key = http.headers.get('idempotency-key')
    if key and len(key) > 160:
        raise HTTPException(400, 'Idempotency key too long')
    key = work_id + ':queue:' + key if key else None
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        work = row(db, Work, work_id)
        if key:
            existing = db.query(RequestQueue).filter_by(command_key=key).first()
            if existing:
                if existing.command_hash != fingerprint:
                    raise HTTPException(409, 'Idempotency key was used with different input')
                return view(db, existing)
        available_work(db, work)
        if body.condition == 'AT_TIME' and utc(body.due_at) <= now():
            raise HTTPException(400, '현재보다 이후의 실행 시각을 선택하세요')
        if body.predecessor_run_id:
            parent = row(db, Run, body.predecessor_run_id)
            if parent.work_id != work.id or parent.is_query or parent.operation in {'reference', 'import'}:
                raise HTTPException(400, '같은 Work의 일반 실행 / Workflow Task를 선행 Run으로 선택하세요')
        thread = row(db, ThreadRecord, body.context_thread_id) if body.context_thread_id else None
        if thread and (thread.work_id != work.id or thread.status == 'EPHEMERAL'):
            raise HTTPException(403, '현재 Work의 저장된 대화 자료만 예약할 수 있습니다')
        scope = thread or SimpleNamespace(id=None, parent_thread_id=None, turn_count=0, usage='{}', compact_state='NONE')
        profile = resolve(catalog, inherited(db, work), body.execution_profile.model_dump(exclude_none=True) if body.execution_profile else {})
        worker_profile(profile)
        config = {key: getattr(body, key) for key in ('resource_ids', 'exclude_resource_ids', 'pack_id', 'budget', 'allow_over_budget','context_policies')}
        config.update(instruction=body.instruction, strategy='FRESH_CONTEXT')
        config = freeze_context(db, work, scope, config, body.context_ids, body.artifact_ids)
        for kind, keys in [('SOURCE', body.context_ids), ('ARTIFACT', body.artifact_ids)]:
            if len(keys) != len(set(keys)):
                raise HTTPException(400, '선택한 자료에 중복 항목이 있습니다')
            config['snapshots'].extend(snapshot(db, work, kind, key, scope.id,body.context_policies.get(kind+':'+key)) for key in keys)
        # Queue freezes IDs, hashes and the small FULL text only. Large file bytes
        # remain in Materials / Artifacts and are checked again at dispatch.
        config['budget_report']['estimate'] += sum(prompt_cost(item)//4 for item in config['snapshots'] if item['source_type'] in {'SOURCE','ARTIFACT'})
        config['queue_snapshot'] = True
        request = Request(id=ident('req'), work_id=work.id, instruction=body.instruction,
                          context_ids=json.dumps(body.context_ids), artifact_ids=json.dumps(body.artifact_ids))
        db.add(request); db.flush()
        job = RequestQueue(id=ident('queue'), work_id=work.id, request_id=request.id,
            condition=body.condition, due_at=utc(body.due_at) if body.due_at else None,
            predecessor_run_id=body.predecessor_run_id, execution_profile=json.dumps(profile),
            context_config=json.dumps(config, ensure_ascii=False), command_key=key, command_hash=fingerprint)
        db.add(job); db.flush(); db.commit()
        result = view(db, job)
    runner.wake.set()
    return result


def trigger(db, job):
    work = row(db, Work, job.work_id)
    available_work(db, work)
    if db.query(Run.id).filter_by(safety_block=True).first():
        raise HTTPException(409, '실행 결과가 불확정인 Run을 먼저 확인하세요')
    request = row(db, Request, job.request_id)
    profile, config = json.loads(job.execution_profile), json.loads(job.context_config)
    run = queue_run(db, work, request.instruction, json.loads(request.context_ids), profile['model'], profile['reasoning'],
        SimpleNamespace(headers={}), request=request, artifact_ids=json.loads(request.artifact_ids),
        execution_profile=profile, frozen_context=config, commit=False,
        command_identity=('request-queue:' + job.id, job.command_hash))
    job.run_id, job.status, job.triggered_at, job.blocked_reason = run.id, 'TRIGGERED', now(), None
    return run


def process_queue(at=None):
    """One atomic claim and Run creation; restart cannot duplicate a submission."""
    at = utc(at or now())
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        jobs = db.query(RequestQueue).options(defer(RequestQueue.context_config), defer(RequestQueue.execution_profile)).filter(RequestQueue.status.in_(['PENDING', 'BLOCKED']))\
            .order_by(RequestQueue.created_at, RequestQueue.id).all()
        for job in jobs:
            if job.blocked_reason == 'PREDECESSOR_NOT_SUCCEEDED':
                continue  # Explicit cancellation or manual execution is required.
            if job.condition == 'AT_TIME' and utc(job.due_at) > at:
                continue
            if job.condition.startswith('AFTER_RUN_'):
                parent = row(db, Run, job.predecessor_run_id)
                if parent.status not in TERMINAL:
                    continue
                if job.condition == 'AFTER_RUN_SUCCEEDED' and parent.status != 'COMPLETED':
                    job.status, job.blocked_reason = 'BLOCKED', 'PREDECESSOR_NOT_SUCCEEDED'
                    continue
            try:
                with db.begin_nested():
                    trigger(db, job)
            except (HTTPException, ValueError, OSError) as exc:
                job.status, job.blocked_reason = 'BLOCKED', str(getattr(exc, 'detail', str(exc)))[:1000]
        db.commit()


@router.post('/request-queue/{queue_id}/cancel')
def cancel(queue_id: str):
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        job = row(db, RequestQueue, queue_id)
        if job.status == 'TRIGGERED':
            raise HTTPException(409, '실행이 이미 생성되었습니다. Run 취소를 사용하세요')
        job.status, job.blocked_reason = 'CANCELLED', None
        db.commit()
        return view(db, job)


@router.post('/request-queue/{queue_id}/execute', status_code=202)
def manual_execute(queue_id: str):
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        job = row(db, RequestQueue, queue_id)
        if job.status not in {'PENDING', 'BLOCKED'}:
            raise HTTPException(409, '대기 / BLOCKED 항목만 수동 실행할 수 있습니다')
        trigger(db, job)
        db.commit()
        result = view(db, job)
    runner.wake.set()
    return result
