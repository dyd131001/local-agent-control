"""Transaction-neutral creation shared by standalone requests and Workflow tasks."""
import json
from .db import Request, Run, Work, add_event
from .storage import runtime_root, workspace_root
from .workspace import ident
from .execution_settings import legacy_profile


def create_run(db, work_id, instruction, context_ids, artifact_ids, model, reasoning,
               *, operation="new", parent=None, request=None, command_key=None, command_hash=None, frozen_workspace=None,
               execution_profile=None, context_config=None, conversation=None, frozen_context=None):
    if request is None:
        request = Request(id=ident("req"), work_id=work_id, instruction=instruction,
                          context_ids=json.dumps(context_ids), artifact_ids=json.dumps(artifact_ids))
        db.add(request)
        db.flush()
    run = Run(id=ident("run"), work_id=work_id, request_id=request.id,
              operation=operation, parent_run_id=parent.id if parent else None,
              thread_id=parent.thread_id if parent and operation == "resume" else None,
              model=model, reasoning=reasoning, command_key=command_key, command_hash=command_hash)
    if operation != "reference":
        profile = execution_profile or legacy_profile(model, reasoning)
        run.model, run.reasoning = profile["model"], profile["reasoning"]
        run.execution_profile = json.dumps(profile)
    db.add(run)
    work = db.get(Work, work_id)
    run.manifest = json.dumps({"storage_root": str(runtime_root(work)), "workspace_root": frozen_workspace or str(workspace_root(work)),
                               "storage_layout": work.storage_layout})
    db.flush()
    from .conversation import attach_run
    attach_run(db, run, work, instruction, context_ids, artifact_ids, context_config, conversation, parent, frozen_context=frozen_context)
    return run
