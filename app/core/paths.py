"""Application resource and per-user data locations."""
from __future__ import annotations

import os
import sys
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


def ensure_data_dirs() -> None:
    for path in (
        DATA_DIR,
        CACHE_DIR,
        LOG_DIR,
        RUNTIME_DIR,
        PLUGIN_DATA_DIR,
        INSTALLED_PLUGINS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def require_supported_platform() -> None:
    if sys.platform != "win32":
        raise RuntimeError("BNU-ToolBox 当前仅支持 Windows 11")
    if sys.getwindowsversion().build < 22000:
        raise RuntimeError("BNU-ToolBox 当前仅支持 Windows 11")
