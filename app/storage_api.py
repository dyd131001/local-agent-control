"""Explicit local workspace and document commands under the existing API guard."""
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .config import DATA_DIR, ROOT, RUNTIME_DIR, STATE_DIR, WORKSPACE_ROOT
from .db import Artifact, Session, Work, dump
from .storage import change_workspace, register_reference, validate_workspace, workspace_root
from .workflow import COMMAND_LOCK, row
from .workspace import safe_child

router = APIRouter(prefix="/api")


class StorageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceBody(StorageBody):
    workspace_path: str


class FolderPickerBody(StorageBody):
    purpose: Literal["WORKSPACE", "PARENT", "EXTERNAL"] = "WORKSPACE"


class ExternalRootBody(StorageBody):
    path: str
    browse: bool = True
    read: bool = False
    ignore_patterns: list[str] = Field(default_factory=list, max_length=100)


class ExternalBody(StorageBody):
    path: str


class DocumentBody(StorageBody):
    relative_path: str = Field(min_length=1, max_length=500)
    content: str = Field(default="", max_length=2000000)
    usage_type: Literal["MARKDOWN", "AGENTS", "REQUIREMENTS", "ARCHITECTURE", "IMPLEMENTATION_PLAN", "DECISION"] = "MARKDOWN"


class ArtifactBody(StorageBody):
    location_type: Literal["WORKSPACE", "EXTERNAL"] = "WORKSPACE"
    path: str


class FolderArtifactBody(StorageBody):
    root: str
    paths: list[str] = Field(min_length=1, max_length=100)


def active_work(db, work_id):
    work = row(db, Work, work_id)
    if work.archived:
        raise HTTPException(409, "Work is archived")
    return work


def external_file(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError("Choose an existing regular external file")
    path = path.resolve(strict=True)
    if path.is_relative_to(STATE_DIR) or path.is_relative_to(RUNTIME_DIR) or path.is_relative_to(DATA_DIR):
        raise ValueError("Internal files cannot be registered as external references")
    return path


@router.get("/storage/settings")
def settings():
    return {"workspace_root": str(WORKSPACE_ROOT), "application_root": str(ROOT),
            "state_root": str(STATE_DIR), "shared_root": str(DATA_DIR / "shared")}


@router.post("/storage/pick-folder")
def pick_folder(body: FolderPickerBody = FolderPickerBody()):
    if sys.platform != "darwin":
        raise HTTPException(422, "Enter a folder path on this platform")
    try:
        result = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Work Workspace 선택")'],
                                capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "폴더 선택 시간이 초과되었습니다. 다시 선택하세요.")
    if result.returncode:
        if "-128" in result.stderr: return {"path": None}
        raise HTTPException(422, "폴더 선택기를 열 수 없습니다. 경로를 직접 입력할 수 있습니다.")
    if body.purpose == 'EXTERNAL':
        from .path_inputs import validate_external_root
        try:
            return {"path": str(validate_external_root(result.stdout.strip()))}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if body.purpose == 'PARENT':
        parent = Path(result.stdout.strip()).expanduser().resolve(strict=True)
        if not parent.is_dir() or any(parent == p or parent.is_relative_to(p) for p in (STATE_DIR, DATA_DIR, RUNTIME_DIR)):
            raise HTTPException(422, "Workspace 생성 위치로 사용할 수 없는 폴더입니다.")
        return {"path": str(parent)}
    return {"path": str(validate_workspace(result.stdout.strip()))}


@router.get('/works/{work_id}/external-roots')
def list_external_roots(work_id: str):
    from .root_scopes import roots
    with Session() as db:
        return roots(row(db, Work, work_id))


@router.get('/runtime/read-root-capability')
def read_root_capability():
    from .gateway import CodexGateway
    return CodexGateway.read_root_capability()


@router.post('/works/{work_id}/external-roots', status_code=201)
def set_external_root(work_id: str, body: ExternalRootBody):
    from .root_scopes import add
    from .path_inputs import validate_ignore_pattern
    try:
        patterns = [validate_ignore_pattern(value) for value in body.ignore_patterns]
        with COMMAND_LOCK, Session() as db:
            work = active_work(db, work_id)
            item = add(work, body.path, body.browse, body.read, patterns)
            db.commit()
            return item
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/works/{work_id}/workspace")
def set_workspace(work_id: str, body: WorkspaceBody):
    with COMMAND_LOCK, Session() as db:
        work = active_work(db, work_id)
        change_workspace(db, work, body.workspace_path)
        db.commit()
        return dump(work)


@router.post("/storage/pick-files")
def pick_files():
    if sys.platform != "darwin":
        raise HTTPException(422, "이 환경에서는 파일 업로드 또는 경로 입력을 사용하세요.")
    script = '''set chosen to choose file with prompt "참고 자료 선택" with multiple selections allowed
set paths to ""
repeat with selectedFile in chosen
set paths to paths & POSIX path of selectedFile & linefeed
end repeat
return paths'''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "파일 선택 시간이 초과되었습니다. 다시 선택하세요.")
    if result.returncode:
        if "-128" in result.stderr: return {"paths": []}
        raise HTTPException(422, "파일 선택기를 열 수 없습니다. 파일 업로드 또는 경로 입력을 사용하세요.")
    return {"paths": [str(external_file(p)) for p in result.stdout.splitlines() if p]}


@router.get("/works/{work_id}/workspace/access")
def workspace_access(work_id: str):
    with Session() as db:
        work = row(db, Work, work_id)
        root = workspace_root(work)
        legacy = work.storage_layout == 'LEGACY' and root == Path(work.path)
    available = False
    issue = None
    try:
        if legacy:
            if root.is_symlink() or not root.is_dir(): raise ValueError('Legacy workspace is unavailable')
            root = root.resolve(strict=True)
            if any(root == p or root.is_relative_to(p) for p in (STATE_DIR, RUNTIME_DIR)):
                raise ValueError('Internal state is not a workspace')
        else:
            root = validate_workspace(str(root))
        available = True
    except (ValueError, OSError):
        issue = "연결된 폴더가 없거나 접근할 수 없습니다. 다른 폴더를 선택하세요."
    readable = available and os.access(root, os.R_OK | os.X_OK)
    writable = available and os.access(root, os.W_OK | os.X_OK)
    if available and not readable:
        issue = "폴더를 읽을 권한이 없습니다. Finder에서 권한을 확인하거나 다른 폴더를 연결하세요."
    elif available and not writable:
        issue = "폴더에 쓸 권한이 없습니다. 결과물 저장을 위해 권한을 확인하거나 다른 폴더를 연결하세요."
    return {"path": str(root), "available": available, "readable": readable, "writable": writable,
            "issue": issue, "execution_scope": "RUN_WORKSPACE"}


@router.post("/works/{work_id}/workspace/open")
def open_workspace(work_id: str):
    with Session() as db:
        path = validate_workspace(str(workspace_root(row(db, Work, work_id))))
    executable = "open" if sys.platform == "darwin" else "xdg-open"
    result = subprocess.run([executable, str(path)], capture_output=True, timeout=10)
    if result.returncode:
        raise HTTPException(422, "Could not open workspace in the file manager")
    return {"opened": True}


@router.get("/works/{work_id}/workspace/files")
def list_files(work_id: str, path: str = ""):
    with Session() as db:
        root = validate_workspace(str(workspace_root(row(db, Work, work_id))))
    directory = safe_child(root, path) if path else root
    if not directory.is_dir():
        raise HTTPException(404, "Directory not found")
    entries = []
    for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.is_symlink() or item.name.startswith('.'):
            continue
        if any(item.resolve() == managed or item.resolve().is_relative_to(managed) for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
            continue
        entries.append({"path": item.relative_to(root).as_posix(), "name": item.name, "is_directory": item.is_dir()})
        if len(entries) >= 500:
            break
    return {"path": path, "entries": entries}


@router.post("/works/{work_id}/sources/external", status_code=201)
def add_external(work_id: str, body: ExternalBody):
    path = external_file(body.path)
    with COMMAND_LOCK, Session() as db:
        work = active_work(db, work_id)
        source = register_reference(db, work, path.parent, path.name, "EXTERNAL")
        db.commit()
        return dump(source)


@router.post("/works/{work_id}/documents", status_code=201)
def create_document(work_id: str, body: DocumentBody):
    with COMMAND_LOCK, Session() as db:
        work = active_work(db, work_id)
        root = validate_workspace(str(workspace_root(work)))
        path = safe_child(root, body.relative_path)
        if any(part.startswith('.') for part in Path(body.relative_path).parts) or path.suffix.lower() != ".md":
            raise ValueError("Choose a relative Markdown file path")
        if path.name == "AGENTS.md" and body.usage_type != "AGENTS":
            raise ValueError("Choose the AGENTS document type explicitly")
        if body.usage_type == "AGENTS" and path.name != "AGENTS.md":
            raise ValueError("AGENTS documents must be named AGENTS.md")
        if any(path.resolve().is_relative_to(managed) for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
            raise ValueError("Documents must be workspace files")
        if path.exists():
            raise HTTPException(409, "File already exists; existing content is preserved")
        data = body.content.encode('utf-8')
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation preserves a file created by the user during validation.
        with path.open('xb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        source = register_reference(db, work, root, body.relative_path, "WORKSPACE", usage_type=body.usage_type)
        db.commit()
        return dump(source)


@router.post("/works/{work_id}/artifacts/reference", status_code=201)
def register_artifact(work_id: str, body: ArtifactBody):
    from .run_service import create_run
    from .workspace import ident, mime_type, safe_read, sha
    with COMMAND_LOCK, Session() as db:
        work = active_work(db, work_id)
        if body.location_type == "WORKSPACE":
            root, relative = validate_workspace(str(workspace_root(work))), body.path
            path = safe_child(root, relative)
            if any(path.resolve().is_relative_to(managed) for managed in (DATA_DIR, STATE_DIR, RUNTIME_DIR)):
                raise ValueError("Internal files cannot be registered as workspace results")
        else:
            path = external_file(body.path)
            root, relative = path.parent, path.name
        content = safe_read(root, relative)
        existing = db.query(Artifact).filter(Artifact.work_id == work.id,
            ((Artifact.location_type == body.location_type) & (Artifact.location_root == str(root)) & (Artifact.relative_path == relative)) |
            (Artifact.origin_path == str(root / relative))).first()
        if existing:
            if existing.sha256 != sha(content):
                raise HTTPException(409, "Existing artifact bytes changed")
            return dump(existing)
        # A manual registration is an execution record without a Runtime Turn.
        run = create_run(db, work.id, "Register existing result: " + relative, [], [], "manual", "none", operation="reference")
        run.status = run.phase = "COMPLETED"
        from .db import now
        run.completed_at, run.artifact_state = now(), "READY"
        artifact = Artifact(id=ident('art'), work_id=work.id, run_id=run.id, name=Path(relative).name,
                            candidate_path=relative, relative_path=relative, location_type=body.location_type,
                            location_root=str(root), origin_path=str(root / relative), content_type=mime_type(relative),
                            size=len(content), sha256=sha(content), partial=False, availability="AVAILABLE")
        db.add(artifact)
        db.commit()
        return dump(artifact)


@router.post('/works/{work_id}/artifacts/folder', status_code=201)
def register_folder_artifact(work_id: str, body: FolderArtifactBody):
    """Freeze selected external files as one archive with their relative paths."""
    import io
    import json
    import zipfile
    from .config import ARTIFACT_LIMIT
    from .db import now
    from .path_inputs import scope_preview
    from .root_scopes import registered
    from .run_service import create_run
    from .storage import runtime_root
    from .workspace import ident, safe_read, sha
    with Session() as db:
        work = active_work(db, work_id)
        try:
            root, permission = registered(work, body.root, 'browse')
            if not permission.get('read'):
                raise ValueError('Bundle Artifact를 만들려면 이 Root의 AI 읽기 권한이 필요합니다.')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    selected = scope_preview(root, body.paths, body.paths, custom=permission.get('ignore_patterns', []))
    files = selected['search_files']
    if not files or len(files) > 1000:
        raise HTTPException(422, '선택한 폴더의 파일은 1~1000개여야 합니다.')
    memory = io.BytesIO()
    total = 0
    included = []
    created = now().isoformat()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in files:
            if relative == '__control_center_bundle__/manifest.json':
                raise HTTPException(422, '묶음 manifest 경로와 같은 파일은 선택할 수 없습니다.')
            data = safe_read(root, relative, ARTIFACT_LIMIT)
            total += len(data)
            if total > ARTIFACT_LIMIT:
                raise HTTPException(422, '선택한 폴더의 파일 합계가 64MB를 초과합니다.')
            archive.writestr(relative, data)
            included.append({'path': relative, 'size': len(data), 'sha256': sha(data)})
        manifest = {'version': 1, 'root': str(root), 'selected_paths': body.paths,
                    'included_files': included, 'excluded_files': selected['excluded_files'],
                    'ignored_locations': selected['ignored_locations'],
                    'symlinks_not_followed': selected['symlinks'], 'created_at': created}
        archive.writestr('__control_center_bundle__/manifest.json',
                         json.dumps(manifest, ensure_ascii=False, separators=(',', ':')))
    content = memory.getvalue()
    if len(content) > ARTIFACT_LIMIT:
        raise HTTPException(422, '묶음 Artifact가 64MB를 초과합니다.')
    with COMMAND_LOCK, Session() as db:
        work = active_work(db, work_id)
        archive_id = ident('folder')
        storage = runtime_root(work) / 'manual-inputs' / archive_id
        storage.mkdir(parents=True, exist_ok=False)
        target = storage / 'selected-files.zip'
        try:
            with target.open('xb') as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            run = create_run(db, work.id, 'Register selected folder files: ' + str(root), [], [],
                             'manual', 'none', operation='reference')
            run.status = run.phase = 'COMPLETED'
            run.completed_at, run.artifact_state = now(), 'READY'
            artifact = Artifact(id=ident('art'), work_id=work.id, run_id=run.id,
                                name='selected-files.zip', candidate_path='selected-files.zip',
                                relative_path='selected-files.zip', location_type='EXTERNAL',
                                location_root=str(storage), origin_path=str(root),
                                content_type='application/zip', size=len(content), sha256=sha(content),
                                partial=False, availability='AVAILABLE')
            db.add(artifact)
            db.commit()
            result = dump(artifact)
            result['file_count'] = len(files)
            result['symlink_count'] = len(selected['symlinks'])
            result['bundle_manifest'] = manifest
            return result
        except BaseException:
            target.unlink(missing_ok=True)
            storage.rmdir()
            raise
