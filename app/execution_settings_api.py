"""Minimal settings storage and preview; protected by the application's API guard."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .db import Category, ExecutionDefault, Session, Work
from .execution_settings import ExecutionProfile, capabilities, catalog_from, defaults, inherited, resolve

router = APIRouter(prefix="/api/execution-settings")
runner = None


def configure(shared_runner):
    global runner
    runner = shared_runner
    return router


def owner(db, scope, owner_id):
    if scope == "GLOBAL":
        if owner_id != "global":
            raise HTTPException(422, "Global owner must be global")
        return None
    result = db.get(Work if scope == "WORK" else Category, owner_id)
    if not result:
        raise HTTPException(404, "Settings owner not found")
    return result


@router.get("")
async def settings():
    catalog = await catalog_from(runner.gateway)
    with Session() as db:
        return {**capabilities(catalog), "global_default": defaults(db, "GLOBAL", "global")}


@router.get("/defaults/{scope}/{owner_id}")
def get_defaults(scope: Literal["GLOBAL", "CATEGORY", "WORK"], owner_id: str):
    with Session() as db:
        owner(db, scope, owner_id)
        return defaults(db, scope, owner_id)


@router.put("/defaults/{scope}/{owner_id}")
async def put_defaults(scope: Literal["GLOBAL", "CATEGORY", "WORK"], owner_id: str, body: ExecutionProfile):
    catalog = await catalog_from(runner.gateway)
    # PUT replaces the sparse override. Null removes the field, restoring inheritance.
    profile = body.model_dump(exclude_none=True)
    with Session() as db:
        item_owner = owner(db, scope, owner_id)
        parent = {} if scope == "GLOBAL" else defaults(db, "GLOBAL", "global")
        if scope == "WORK":
            parent.update(defaults(db, "CATEGORY", item_owner.category_id))
        from .workflow_operations import worker_profile
        worker_profile(resolve(catalog, parent, profile))
        item = db.get(ExecutionDefault, (scope, owner_id))
        if item is None:
            item = ExecutionDefault(scope=scope, owner_id=owner_id)
            db.add(item)
        item.profile = json.dumps(profile)
        db.commit()
        return profile


class ResolveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_id: str | None = None
    execution_profile: ExecutionProfile = Field(default_factory=ExecutionProfile)


@router.post("/resolve")
async def preview(body: ResolveBody):
    catalog = await catalog_from(runner.gateway)
    with Session() as db:
        work = owner(db, "WORK", body.work_id) if body.work_id else None
        return resolve(catalog, inherited(db, work), body.execution_profile.model_dump(exclude_none=True))
