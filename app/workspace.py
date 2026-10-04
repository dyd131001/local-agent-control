"""Backend-owned local storage, immutable context snapshots and verified artifacts."""
import hashlib
import importlib.metadata
import json
import mimetypes
import os
import stat
import uuid
from pathlib import Path
from .config import ARTIFACT_LIMIT, DATA_DIR, STATE_DIR, UPLOAD_LIMIT
from .db import Artifact, Source, now
from .gateway import RULES, SETTINGS
from .storage import runtime_root, workspace_root, file_bytes


def ident(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def mime_type(name):
    # Python 3.10/macOS catalogs do not consistently recognize Markdown.
    if Path(name).suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def safe_child(root: Path, relative: str) -> Path:
    root = root.absolute()
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in {"..", "."} for p in path.parts):
        raise ValueError("Invalid relative path")
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Symlink paths are not allowed")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path is outside the managed directory")
    return candidate


def safe_read(root: Path, relative: str, limit=ARTIFACT_LIMIT):
    """Open each path component with O_NOFOLLOW, including the directory root."""
    safe_child(root, relative)
    parts = Path(relative).parts
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as file:
            before = os.fstat(file.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("Not a regular file or file exceeds size limit")
            data = file.read(limit + 1)
            after = os.fstat(file.fileno())
            if len(data) > limit or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("File changed during verification")
            return data
    finally:
        os.close(fd)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{uuid.uuid4().hex}.tmp"
    try:
        with open(temp, "xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def work_dir(category_id, work_id):
    return safe_child(DATA_DIR, f"categories/{category_id}/works/{work_id}")


def provision_work(work):
    if work.storage_layout == "EXTERNAL":
        from .storage import validate_workspace
        validate_workspace(str(workspace_root(work)))
        return
    root = Path(work.path)
    if not root.resolve().is_relative_to(DATA_DIR) or root.is_symlink():
        raise ValueError("Invalid Work directory")
    for name in ("sources", "context", "decisions", "artifacts", "runs"):
        safe_child(root, name).mkdir(parents=True, exist_ok=True)
    if not (root / "AGENTS.md").exists():
        atomic_write(root / "AGENTS.md", RULES.encode())
    metadata = {"id": work.id, "category_id": work.category_id, "name": work.name,
                "description": work.description, "archived": work.archived}
    atomic_write(root / "work.json", json.dumps(metadata, ensure_ascii=False, indent=2).encode())


def register_source(root, work_id, filename, content, content_type, is_context, session, *, location_type="LEGACY"):
    if len(content) > UPLOAD_LIMIT:
        raise ValueError("File exceeds 32 MiB upload limit")
    name = Path(filename.replace("\\", "/")).name
    if name in {"", ".", ".."} or any(ord(c) < 32 for c in name) or len(name.encode()) > 200:
        raise ValueError("Invalid filename")
    source_id = ident("src")
    relative = f"{'context' if is_context and location_type == 'LEGACY' else 'sources'}/{source_id}/{name}"
    dest = safe_child(root, relative)
    atomic_write(dest, content)
    record = Source(id=source_id, work_id=work_id, name=name, relative_path=relative,
                    location_type=location_type, location_root=str(root) if location_type != "LEGACY" else None,
                    content_type=mime_type(name),
                    size=len(content), sha256=sha(content), is_context=is_context)
    session.add(record)
    return record


def prepare_context(work, run, request, sources, source_snapshots=None):
    from .context_policy import policy,short_summary
    from .storage import location_root
    frozen = json.loads(run.manifest)
    root = runtime_root(work, frozen)
    base = safe_child(root, f"runs/{run.id}")
    workspace = safe_child(base, "workspace")
    safe_child(workspace, "artifacts").mkdir(parents=True, exist_ok=True)
    safe_child(workspace, "scratch").mkdir(exist_ok=True)
    files = []
    policies=json.loads(run.context_config or '{}').get('context_policies',{})
    for source in sources:
        previous = (source_snapshots or {}).get(source.id)
        data = safe_read(Path(previous.get("snapshot_root", str(root))), previous["snapshot_path"], UPLOAD_LIMIT) if previous else file_bytes(work, source, UPLOAD_LIMIT)
        if sha(data) != source.sha256:
            raise ValueError(f"Selected Context changed since registration: {source.name}. Upload a new version.")
        mode=policy('SOURCE',source,policies.get('SOURCE:'+source.id))
        source_root=location_root(work,source)
        relative=source.relative_path
        if mode=='FULL':
            relative=f"runs/{run.id}/inputs/{source.id}/{source.name}"
            atomic_write(safe_child(root, relative), data)
            source_root=root
        files.append({"source_id": source.id, "name":source.name, "scope": "work", "original_path": source.relative_path,
                      "snapshot_path": relative, "snapshot_root": str(source_root), "location_type": source.location_type,
                      "sha256": sha(data), "size": len(data),
                      "mime": source.content_type, "include_mode":mode,"summary":short_summary(source.name,source.content_type,data),
                      "delivery": "inline" if mode=='FULL' else "reference"})
    rules = RULES.encode() if work.storage_layout == "EXTERNAL" else safe_read(root, "AGENTS.md", UPLOAD_LIMIT)
    atomic_write(workspace / "AGENTS.md", rules)
    context = "\n".join(f"- {Path(f['snapshot_root']) / f['snapshot_path']} (sha256 {f['sha256']})" for f in files)
    prompt = (request.instruction + "\n\nSelected reference files (local snapshots; read them as needed):\n" +
              (context or "(none)") + f"\n\nCurrent writable workspace: {workspace}. "
              "Save all deliverables inside its artifacts/ directory. Verify files on disk before reporting success. "
              "Earlier Run paths in conversation history are read-only; create new results in this Run.")
    manifest = {"schema_version": 1, "run_id": run.id, "request_id": request.id, "work_id": work.id,
                "storage_root": str(root), "storage_layout": frozen.get("storage_layout", work.storage_layout),
                "workspace_root": frozen.get("workspace_root", str(workspace_root(work))),
                "parent_run_id": run.parent_run_id, "thread_id": run.thread_id, "created_at": now().isoformat(),
                "instruction": request.instruction, "instruction_sha256": sha(request.instruction.encode()),
                "prompt": prompt, "prompt_sha256": sha(prompt.encode()), "files": files,
                "model_requested": run.model, "effort_requested": run.reasoning,
                "cwd": str(workspace), "approval_mode": "deny_all", "sandbox": SETTINGS,
                "sdk_version": importlib.metadata.version("openai-codex"),
                "runtime_version": importlib.metadata.version("openai-codex-cli-bin"),
                "agents_sha256": sha(rules), "delivery_scope": "provided context; inherited thread/user configuration is not fully frozen"}
    save_manifest(run.id, manifest)
    return manifest


def save_manifest(run_id, manifest):
    atomic_write(STATE_DIR / "manifests" / f"{run_id}.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())


def scan_files(workspace, output_root=None):
    """Bounded result scan. Reject links/special/unstable files, never follow them."""
    root = output_root if output_root is not None else safe_child(workspace, "artifacts")
    if not root.exists():
        return []
    files, total = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Symlink directory in artifacts")
        for name in sorted(names):
            relative = str((Path(directory) / name).relative_to(root))
            data = safe_read(root, relative)
            total += len(data)
            if len(files) >= 1000 or total > 256 * 1024 * 1024:
                raise ValueError("Artifact collection exceeds 1000 files or 256 MiB")
            files.append((relative, data, sha(data)))
    return files


def collect_artifacts(root, work_id, run_id, workspace, partial=False, output_root=None, *, destination_root=None):
    records = []
    for relative, data, digest in scan_files(workspace, output_root):
        # Full content hash + path hash preserves files sharing the same bytes/name.
        name = Path(relative).name
        target = f"outputs/{run_id}/{relative}" if destination_root else f"artifacts/{run_id}/{sha(relative.encode())[:16]}-{digest}/{name}"
        destination = Path(destination_root) if destination_root else root
        dest = safe_child(destination, target)
        if dest.exists():
            if sha(safe_read(destination, target)) != digest:
                raise ValueError("Published Artifact was modified; refusing to overwrite")
        else:
            atomic_write(dest, data)
        records.append(Artifact(id="art_" + sha((run_id + target).encode())[:24], work_id=work_id, run_id=run_id,
            name=name, candidate_path=relative, relative_path=target,
            location_type="WORKSPACE" if destination_root else "LEGACY", location_root=str(destination) if destination_root else None,
            origin_path=str(dest) if destination_root else None,
            staging_path=str((output_root or safe_child(workspace, "artifacts")) / relative) if destination_root else None,
            content_type=mime_type(name),
            size=len(data), sha256=digest, partial=partial, availability="AVAILABLE"))
    return records
