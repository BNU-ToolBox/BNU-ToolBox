"""Application resource and per-user data locations."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

APP_NAME = "BNU-ToolBox"
ROOT = Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    override = str(os.environ.get("BNU_TOOLBOX_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        return Path(local) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


DATA_DIR = _default_data_dir()
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
RUNTIME_DIR = DATA_DIR / "runtime"
PLUGIN_DATA_DIR = DATA_DIR / "plugins"
INSTALLED_PLUGINS_DIR = DATA_DIR / "installed-plugins"
UPDATE_DIR = DATA_DIR / "updates"
LOG_TOTAL_LIMIT = 1_000_000


def ensure_data_dirs() -> None:
    for path in (
        DATA_DIR,
        CACHE_DIR,
        LOG_DIR,
        RUNTIME_DIR,
        PLUGIN_DATA_DIR,
        INSTALLED_PLUGINS_DIR,
        UPDATE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def trim_logs(max_total_bytes: int = LOG_TOTAL_LIMIT) -> int:
    """Keep the complete log directory near 1 MB, deleting oldest files first."""
    if not LOG_DIR.is_dir():
        return 0
    files = sorted(
        (path for path in LOG_DIR.rglob("*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    total = sum(path.stat().st_size for path in files)
    removed = 0
    for path in files:
        if total <= max_total_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
            removed += size
        except OSError:
            # The active console log cannot be removed while open. Rotating
            # plugin handlers and the next startup cleanup bound its growth.
            continue
    return removed


def start_log_maintenance() -> None:
    """Clean oversized log storage at startup and periodically thereafter."""
    import threading

    def worker() -> None:
        while True:
            try:
                trim_logs()
            except OSError:
                pass
            time.sleep(60)

    threading.Thread(
        target=worker, daemon=True, name="log-maintenance",
    ).start()


def require_supported_platform() -> None:
    if sys.platform != "win32":
        raise RuntimeError("BNU-ToolBox 当前仅支持 Windows 11")
    if sys.getwindowsversion().build < 22000:
        raise RuntimeError("BNU-ToolBox 当前仅支持 Windows 11")
