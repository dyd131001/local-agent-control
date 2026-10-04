"""Durable time triggers. Creates WorkflowRuns through the existing Engine only."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

from fastapi import HTTPException

from .db import DelayedResume, ScheduleFire, Session, WorkflowSchedule, now
from .workflow import COMMAND_LOCK
from .workflow_operations import transaction, trigger_delay, utc
from .workspace import ident


def claim_due(at=None):
    at = utc(at or now())
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        for schedule in db.query(WorkflowSchedule).filter(WorkflowSchedule.enabled.is_(True), WorkflowSchedule.next_fire_at <= at).order_by(WorkflowSchedule.next_fire_at).limit(20):
            due = utc(schedule.next_fire_at)
            late = (at-due).total_seconds()
            skipped = late > schedule.grace_seconds and schedule.misfire_policy == "SKIP"
            fire = db.query(ScheduleFire).filter_by(schedule_id=schedule.id, scheduled_for=due).first()
            if not fire:
                db.add(ScheduleFire(id=ident("fire"), schedule_id=schedule.id, scheduled_for=due,
                                    status="SKIPPED" if skipped else "CLAIMED", retry_at=at,
                                    error="MISFIRE_SKIPPED" if skipped else None))
            # Advance from the original anchor, coalescing missed repeats into one occurrence.
            if schedule.kind == "RECURRING":
                count = max(1, int(late // schedule.interval_seconds)+1)
                schedule.next_fire_at = due+timedelta(seconds=count*schedule.interval_seconds)
            else:
                schedule.next_fire_at = None
                if skipped:
                    schedule.enabled = False
        db.commit()
        return [item.id for item in db.query(ScheduleFire).filter(ScheduleFire.status == "CLAIMED", ScheduleFire.retry_at <= at).order_by(ScheduleFire.scheduled_for).limit(20)]


def process_delays(at=None):
    at = utc(at or now())
    with COMMAND_LOCK, Session() as db:
        transaction(db)
        for job in db.query(DelayedResume).filter(DelayedResume.status == "PENDING", DelayedResume.due_at <= at).order_by(DelayedResume.due_at).limit(20):
            try:
                with db.begin_nested():
                    trigger_delay(db, job)
            except HTTPException as exc:
                # Unknown Runtime outcomes / archived Work require user resolution.
                job.error = str(exc.detail)
                if exc.status_code != 409:
                    job.status = "FAILED"
            except (ValueError, OSError) as exc:
                job.status, job.error = "FAILED", str(exc)[:1000]
        db.commit()


async def dispatch_due(runner, at=None):
    from .workflow_api import StartBody, start_managed_execution
    fires = await asyncio.to_thread(claim_due, at)
    for fire_id in fires:
        with Session() as db:
            fire = db.get(ScheduleFire, fire_id)
            schedule = db.get(WorkflowSchedule, fire.schedule_id)
            workflow_id, body = schedule.workflow_definition_id, json.loads(schedule.context)
        try:
            await start_managed_execution(workflow_id, StartBody(**body),
                SimpleNamespace(headers={"idempotency-key":"schedule:"+fire_id}), schedule_fire_id=fire_id)
        except Exception as exc:
            with COMMAND_LOCK, Session() as db:
                transaction(db)
                fire = db.get(ScheduleFire, fire_id)
                if fire.status == "CLAIMED":
                    if isinstance(exc, HTTPException) and exc.status_code in {409, 503}:
                        fire.retry_at = now()+timedelta(seconds=60)
                    else:
                        fire.status = "FAILED"
                        schedule=db.get(WorkflowSchedule,fire.schedule_id)
                        if schedule.kind == "ONE_TIME":
                            schedule.enabled=False
                    fire.error = str(getattr(exc, "detail", type(exc).__name__))[:1000]
                    db.commit()
    await asyncio.to_thread(process_delays, at)
    from .request_queue import process_queue
    await asyncio.to_thread(process_queue, at)
