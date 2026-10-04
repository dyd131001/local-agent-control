"""Application, workspace, state and published storage have separate roots."""
import os
import hashlib
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("CONTROL_CENTER_ROOT", Path.cwd())).expanduser().resolve()
legacy_state = ROOT / ".control-center-state"
state_default = legacy_state if (legacy_state / "control.db").exists() else Path.home() / ".control-center"
STATE_DIR = Path(os.environ.get("CONTROL_CENTER_STATE", state_default)).expanduser().resolve()
DATA_DIR = Path(os.environ.get("CONTROL_CENTER_DATA", ROOT / "data")).expanduser().resolve()
SHARED_DIR = DATA_DIR / "shared"
WORKSPACE_ROOT = Path(os.environ.get("CONTROL_CENTER_WORKSPACE_ROOT", Path.home() / "Developer")).expanduser().resolve()
runtime_default = Path(tempfile.gettempdir()) / ("control-center-runtime-" + hashlib.sha256(str(STATE_DIR).encode()).hexdigest()[:12])
RUNTIME_DIR = Path(os.environ.get("CONTROL_CENTER_RUNTIME", runtime_default)).expanduser().resolve()
if STATE_DIR == DATA_DIR or STATE_DIR.is_relative_to(DATA_DIR):
    raise ValueError("CONTROL_CENTER_STATE must be outside CONTROL_CENTER_DATA")
if any(RUNTIME_DIR == managed or RUNTIME_DIR.is_relative_to(managed) or managed.is_relative_to(RUNTIME_DIR)
       for managed in (STATE_DIR, DATA_DIR)):
    raise ValueError("CONTROL_CENTER_RUNTIME must be separate from state and shared data")
DB_PATH = STATE_DIR / "control.db"
SESSION_PATH = STATE_DIR / "session.token"
UPLOAD_LIMIT = 32 * 1024 * 1024
ARTIFACT_LIMIT = 64 * 1024 * 1024
MAX_PREVIEW = 2 * 1024 * 1024
STATIC_DIR = Path(__file__).parent / "static"
MAX_PARALLEL_TASKS = int(os.environ.get("CONTROL_CENTER_MAX_PARALLEL_TASKS", "3"))
if MAX_PARALLEL_TASKS < 1:
    raise ValueError("CONTROL_CENTER_MAX_PARALLEL_TASKS must be positive")
for directory in (STATE_DIR, DATA_DIR):
    directory.mkdir(parents=True, exist_ok=True)
