"""Runtime-backed profiles shared by every execution entry point."""
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from .db import ExecutionDefault


class ExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    reasoning: str | None = None
    personality: str | None = None
    permission: Literal["read-only", "workspace-write", "full-access"] | None = None
    speed: str | None = None


def override(value):
    """Accept the shared profile and the old model/reasoning request fields."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    value = value or {}
    profile = value.get("execution_profile")
    result = dict(profile or {})
    for key in ("model", "reasoning"):
        if value.get(key) is not None:
            if result.get(key) is not None and result[key] != value[key]:
                raise HTTPException(422, f"Conflicting {key} overrides")
            result[key] = value[key]
    return ExecutionProfile.model_validate(result).model_dump(exclude_none=True)


def defaults(db, scope, owner_id):
    item = db.get(ExecutionDefault, (scope, owner_id))
    return json.loads(item.profile) if item else {}


def inherited(db, work):
    result = defaults(db, "GLOBAL", "global")
    if work:
        result = {**result, **defaults(db, "CATEGORY", work.category_id),
                  **defaults(db, "WORK", work.id)}
    return result


def resolve(catalog, *layers, status_code=422):
    """Null/missing fields inherit. Return a complete, validated snapshot."""
    merged = {}
    for layer in layers:
        merged.update({key: value for key, value in (layer or {}).items() if value is not None})
    profile = ExecutionProfile.model_validate(merged)
    model = next((m for m in catalog if m["id"] == profile.model), None) if profile.model else next((m for m in catalog if m.get("default")), None)
    if not model:
        raise HTTPException(status_code, "Choose a model returned by the Runtime")
    reasoning = profile.reasoning or model["default_reasoning"]
    if reasoning not in model["reasoning"]:
        raise HTTPException(status_code, "Reasoning is not supported by this model")
    # SDK 0.158.0 explicitly deprecates Personality selection (always unsupported).
    if profile.personality is not None:
        raise HTTPException(status_code, "This Runtime does not support Personality selection")
    tiers = model.get("service_tiers", [])
    # TurnStartParams documents "default" as the standard-speed reset, including Resume/Fork.
    speed = profile.speed if profile.speed is not None else model.get("default_service_tier") or "default"
    if speed not in {"default", *(tier["id"] for tier in tiers)}:
        raise HTTPException(status_code, "Speed is not supported by this model")
    return ExecutionProfile(model=model["id"], reasoning=reasoning, personality=None,
                            permission=profile.permission or "workspace-write", speed=speed).model_dump()


def legacy_profile(model, reasoning):
    """Historical rows/snapshots keep their original model and reasoning."""
    return ExecutionProfile(model=model, reasoning=reasoning, permission="workspace-write", speed="default").model_dump()


def run_profile(run):
    return json.loads(run.execution_profile) if run.execution_profile else legacy_profile(run.model, run.reasoning)


async def catalog_from(gateway):
    try:
        return await gateway.models()
    except Exception as exc:
        raise HTTPException(503, "Runtime catalog unavailable") from exc


def capabilities(catalog):
    return {"models": catalog, "permissions": ["read-only", "workspace-write"],
            "runtime_permissions": ["read-only", "workspace-write", "full-access"],
            "permission_restriction":"Full Access execution is blocked to protect control state",
            "personality": {"supported": False, "values": [],
                            "reason": "Personality selection is deprecated in Runtime 0.158.0"},
            "speed": {"supported": True, "standard": "default", "source": "model.service_tiers"},
            "approval_mode": "deny_all"}
