"""Location resolution and explicit workspace operations; legacy paths stay put."""
from pathlib import Path
from .config import DATA_DIR, ROOT, RUNTIME_DIR, STATE_DIR, WORKSPACE_ROOT


def workspace_root(work):
    return Path(work.workspace_path or work.linked_workspace_path or work.path)


def runtime_root(work, manifest=None):
    frozen = (manifest or {}).get("storage_root")
    if frozen:
        root = Path(frozen)
        if root != Path(work.path) and not root.is_relative_to(RUNTIME_DIR):
            raise ValueError("Invalid frozen execution storage root")
        return root
    return RUNTIME_DIR / work.id if getattr(work, "storage_layout", "LEGACY") == "EXTERNAL" else Path(work.path)


def location_root(work, item):
    return Path(item.location_root or work.path)


def file_bytes(work, item, limit=None):
    from .workspace import safe_read
    args = {} if limit is None else {"limit": limit}
    return safe_read(location_root(work, item), item.relative_path, **args)


def validate_workspace(value, *, existing=True):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Workspace root cannot be a symlink")
    try:
        canonical = path.resolve(strict=existing)
    except OSError as exc:
        raise ValueError("Workspace is unavailable") from exc
    if existing and not canonical.is_dir():
        raise ValueError("Workspace must be a directory")
    for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR):
        if canonical == managed or canonical.is_relative_to(managed) or (canonical != ROOT and managed.is_relative_to(canonical)):
            raise ValueError("Workspace and internal storage must not contain each other")
    return canonical


def create_workspace(folder, parent=None):
    from .workspace import safe_child
    if not folder or folder in {".", ".."} or any(c in folder for c in '/\\\x00') or len(folder.encode()) > 200:
        raise ValueError("Choose a single workspace folder name")
    root = Path(parent or WORKSPACE_ROOT).expanduser().resolve()
    path = validate_workspace(str(safe_child(root, folder)), existing=False)
    if path.is_relative_to(ROOT):
        raise ValueError("Create workspaces outside the application repository")
    root.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError as exc:
        raise ValueError("Workspace already exists; choose existing folder instead") from exc
    return path


def register_reference(db, work, root, relative, location_type, *, usage_type="REFERENCE", is_context=True):
    from .db import Source
    from .workspace import ident, mime_type, safe_child, safe_read, sha
    from .config import UPLOAD_LIMIT
    path = safe_child(root, relative)
    if location_type != "LEGACY" and any(path.resolve().is_relative_to(managed) for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
        raise ValueError("Internal storage is not a workspace reference")
    content = safe_read(root, relative, UPLOAD_LIMIT)
    existing = db.query(Source).filter_by(work_id=work.id, location_root=str(root), relative_path=relative,
                                        location_type=location_type).order_by(Source.created_at.desc()).first()
    if existing:
        if existing.sha256 == sha(content):
            return existing
        # Explicit re-registration creates a new source version. Old input IDs
        # retain their original hash and fail preparation if bytes changed.
    source = Source(id=ident("src"), work_id=work.id, name=Path(relative).name, relative_path=relative,
                    location_type=location_type, location_root=str(root), usage_type=usage_type,
                    content_type=mime_type(relative), size=len(content), sha256=sha(content), is_context=is_context)
    db.add(source)
    return source


def change_workspace(db, work, path):
    from fastapi import HTTPException
    from .db import Run, WorkflowRun
    if db.query(Run.id).filter(Run.work_id == work.id, (Run.status.in_(["CREATED", "RUNNING"])) | Run.safety_block.is_(True)).first() or \
       db.query(WorkflowRun.id).filter(WorkflowRun.work_id == work.id, WorkflowRun.status.in_(["CREATED", "RUNNING"])).first():
        raise HTTPException(409, "Finish or cancel active executions before changing workspace")
    work.workspace_path = str(validate_workspace(path))
    work.storage_layout = "EXTERNAL"
    work.workspace_kind = "LINKED"
    work.linked_workspace_path = work.workspace_path
    # work.path and every pre-existing Source/Artifact remain unchanged.


def remove_published_staging(artifact):
    if not artifact.staging_path or artifact.location_type != "SHARED":
        return
    from .workspace import safe_child
    path = Path(artifact.staging_path)
    if path.is_relative_to(RUNTIME_DIR):
        safe_child(RUNTIME_DIR, str(path.relative_to(RUNTIME_DIR))).unlink(missing_ok=True)
