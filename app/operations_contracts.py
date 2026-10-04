"""Versioned response schemas for the future Dashboard and Work Tools UI."""
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict
from .execution_settings import ExecutionProfile

T=TypeVar('T')

class Action(BaseModel):
    model_config=ConfigDict(extra='allow')
    name:str
    method:Literal['GET','POST','PATCH','PUT','DELETE']
    path:str

class Page(BaseModel,Generic[T]):
    total:int
    items:list[T]
    offset:int
    limit:int
    has_more:bool

class OperationItem(BaseModel):
    model_config=ConfigDict(extra='allow')
    entity_type:Literal['RUN','TASK','WORKFLOW','APPROVAL','SCHEDULE','SCHEDULE_FIRE','DELAYED_RESUME','THREAD','CONTEXT_PACK','REQUEST_QUEUE']
    id:str
    state:str
    work_id:str
    work_name:str
    category_id:str
    title:str
    updated_at:str|None
    actions:list[Action]
    execution_settings:ExecutionProfile|None=None
    runtime_status:str|None=None
    context:dict[str,Any]|None=None
    usage:dict[str,Any]|None=None
    progress:dict[str,Any]|None=None
    warnings:list[str]|None=None

class StateSummary(BaseModel):
    total:int
    by_entity_type:dict[str,int]

class Scope(BaseModel):
    work_id:str|None
    category_id:str|None
    include_queries:bool

class RuntimeStatus(BaseModel):
    provider:dict[str,Any]
    dispatcher:dict[str,Any]
    executions:list[OperationItem]
    global_execution_block:dict[str,Any]
    usage:Page[dict[str,Any]]
    note:str

class DashboardResponse(BaseModel):
    contract_version:Literal[1]
    generated_at:str
    scope:Scope
    summary:dict[str,StateSummary]
    states:dict[str,Page[OperationItem]]
    workflows:Page[OperationItem]
    approvals:Page[OperationItem]
    scheduled:Page[OperationItem]
    context_warnings:Page[OperationItem]
    recent_runs:Page[OperationItem]
    recent_artifacts:Page[dict[str,Any]]
    usage:Page[dict[str,Any]]
    global_execution_block:dict[str,Any]
    goal:dict[str,Any]
    count_semantics:str
    runtime:RuntimeStatus

class RuntimeResponse(RuntimeStatus):
    contract_version:Literal[1]
    generated_at:str
    scope:Scope

class DiffFile(BaseModel):
    model_config=ConfigDict(extra='allow')
    path:str
    old_path:str|None
    status:str
    additions:int|None
    deletions:int|None
    binary:bool|None

class DiffResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    contract_version:Literal[1]
    available:bool
    work_id:str
    scope:Literal['WORKING_TREE','FILES','BRANCH']
    files:list[DiffFile]
    patch:str|None
    diff_sha256:str|None
    ai_run_created:Literal[False]
    reason:str|None=None
    base_commit:str|None=None
    target_commit:str|None=None
    summary:dict[str,Any]|None=None
    truncated:bool|None=None

class ReviewResponse(BaseModel):
    contract_version:Literal[1]
    run:dict[str,Any]
    context:dict[str,Any]
    tool_context:dict[str,Any]
    result:dict[str,Any]
    actions:list[Action]
