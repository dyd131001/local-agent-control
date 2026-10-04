"""Read-only linked repository inputs; Backend-owned clone and isolated worktrees."""
import io
import json
import os
import subprocess
import threading
import zipfile
from pathlib import Path
from .config import DATA_DIR, STATE_DIR, ARTIFACT_LIMIT
from .workspace import safe_child, safe_read, atomic_write, sha
from .storage import runtime_root, validate_workspace

GIT_LOCK = threading.RLock()


def linked_path(value):
    return str(validate_workspace(value))


def git(args, *, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.fsmonitor=false", *args],
                            cwd=cwd, env=env, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise ValueError("Git workspace operation failed: " + result.stderr.decode(errors="replace")[:500])
    return result.stdout


def baseline(work):
    if not work.linked_workspace_path:
        raise ValueError("Git worktree requires a LINKED project")
    source = linked_path(work.linked_workspace_path)
    return git(["-C", source, "rev-parse", "--verify", "HEAD^{commit}"]).decode().strip()


def prepare(work, run_id, commit, *, root=None):
    root = root or runtime_root(work)
    admin = safe_child(root, "git/repository.git")
    cwd = safe_child(root, f"runs/{run_id}/worktree")
    output = safe_child(root, f"runs/{run_id}/outputs")
    with GIT_LOCK:
        if not admin.exists():
            admin.parent.mkdir(parents=True, exist_ok=True)
            git(["clone", "--bare", "--no-hardlinks", "--", linked_path(work.linked_workspace_path), str(admin)])
        else:
            git(["--git-dir", str(admin), "fetch", "--no-recurse-submodules", "--", linked_path(work.linked_workspace_path), "+refs/heads/*:refs/heads/*"])
        try:
            git(["--git-dir", str(admin), "cat-file", "-e", commit + "^{commit}"])
        except ValueError:
            # A detached HEAD may not be reachable from any branch ref. Fetch
            # only the frozen local commit; never silently choose a newer HEAD.
            git(["--git-dir", str(admin), "fetch", "--no-recurse-submodules", "--no-tags", "--",
                 linked_path(work.linked_workspace_path), commit])
        if cwd.exists():
            raise ValueError("Existing worktree preparation requires reconciliation; refusing overwrite")
        cwd.parent.mkdir(parents=True, exist_ok=True)
        git(["--git-dir", str(admin), "worktree", "add", "--detach", str(cwd), commit])
        # Freeze the administrative path BEFORE the Worker can edit the .git file.
        control = (cwd / ".git").read_text().strip().removeprefix("gitdir: ")
        git_dir = Path(control).resolve()
        if not git_dir.is_relative_to(admin):
            raise ValueError("Invalid worktree administrative path")
        output.mkdir(parents=True, exist_ok=True)
    return {"cwd": str(cwd), "output_root": str(output), "writable_roots": [str(output)],
            "git_base_commit": commit, "git_admin_root": str(admin), "git_dir": str(git_dir)}


def collect_changes(work, manifest):
    root = runtime_root(work, manifest)
    cwd = safe_child(root, str(Path(manifest["cwd"]).relative_to(root)))
    output = safe_child(root, str(Path(manifest["output_root"]).relative_to(root)))
    admin = safe_child(root, "git/repository.git")
    git_dir = Path(manifest["git_dir"])
    safe_child(admin, str(git_dir.relative_to(admin)))
    args = ["--git-dir", str(git_dir), "--work-tree", str(cwd)]
    patch = git(args + ["diff", "--no-ext-diff", "--no-textconv", "--binary", manifest["git_base_commit"], "--"])
    if len(patch) > ARTIFACT_LIMIT:
        raise ValueError("Git patch exceeds artifact limit")
    names = git(args + ["ls-files", "--others", "--exclude-standard", "-z"]).decode().split("\x00")
    newfiles, total = [], 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in filter(None, names):
            data = safe_read(cwd, name)
            total += len(data)
            if len(newfiles) >= 1000 or total > ARTIFACT_LIMIT:
                raise ValueError("New file bundle exceeds artifact limits")
            # Fixed timestamps keep recovery bytes/Artifact IDs stable.
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            bundle.writestr(info, data)
            newfiles.append({"path": name, "sha256": sha(data), "size": len(data)})
    tracked = git(args + ["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", manifest["git_base_commit"], "--"]).decode().split("\x00")
    dest = safe_child(output, "system/git")
    dest.mkdir(parents=True, exist_ok=True)
    atomic_write(dest / "changes.patch", patch)
    atomic_write(dest / "changes.json", json.dumps({"base_commit": manifest["git_base_commit"], "tracked_changes": tracked, "new_files": newfiles}, sort_keys=True).encode())
    atomic_write(dest / "new-files.zip", buffer.getvalue())
