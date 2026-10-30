"""Plugin discovery, archive validation, installation and removal."""
from __future__ import annotations

import json
import shutil
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .paths import INSTALLED_PLUGINS_DIR, PLUGIN_DATA_DIR

_ROOT = Path(__file__).resolve().parents[2]
LEGACY_PLUGINS_DIR = _ROOT / "plugins"
USER_PLUGINS_DIR = INSTALLED_PLUGINS_DIR
MAX_ZIP_MEMBERS = 500
MAX_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

VALID_TYPES = {
    "string", "password", "number", "bool", "choice", "string-list",
    "course-table", "specialty", "object",
}


class PluginError(Exception):
    pass


def _validate_plugin_id(plugin_id: object) -> str:
    if (not isinstance(plugin_id, str) or not plugin_id or len(plugin_id) > 64
            or not all(c.isalnum() or c in "-_" for c in plugin_id)):
        raise PluginError(f"非法插件 id: {plugin_id!r}")
    return plugin_id


def _validate_manifest(manifest: Any, source: str) -> dict:
    if not isinstance(manifest, dict):
        raise PluginError(f"{source}: plugin.json 必须是 JSON 对象")
    for key in ("id", "name", "version", "entry"):
        if not manifest.get(key):
            raise PluginError(f"{source}: plugin.json 缺少必填字段 {key}")
    try:
        _validate_plugin_id(manifest["id"])
    except PluginError as exc:
        raise PluginError(f"{source}: {exc}") from exc
    entry = Path(str(manifest["entry"]))
    if entry.name != str(manifest["entry"]) or entry.suffix != ".py":
        raise PluginError(f"{source}: entry 必须是插件目录内的单文件名 Python 入口")
    schema = manifest.get("config_schema", [])
    if not isinstance(schema, list):
        raise PluginError(f"{source}: config_schema 必须是数组")
    for item in schema:
        if not isinstance(item, dict) or "key" not in item or "label" not in item:
            raise PluginError(f"{source}: config_schema 项需要 key/label")
        if item.get("type", "string") not in VALID_TYPES:
            raise PluginError(f"{source}: 不支持的字段类型 {item.get('type')!r}")
    ui = manifest.get("config_ui")
    if ui is not None:
        if not isinstance(ui, str) or Path(ui).name != ui or Path(ui).suffix != ".html":
            raise PluginError(f"{source}: config_ui 必须是插件目录内的单文件名 .html")
    host = manifest.get("host")
    if host is not None:
        if not isinstance(host, dict) or not isinstance(host.get("min_version", ""), str):
            raise PluginError(f"{source}: host 必须是包含 min_version 的对象")
    return manifest


class PluginManager:
    def __init__(self, runner):
        self._runner = runner
        self._lock = threading.Lock()
        self._ready = False

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        USER_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        # Earlier packages shipped plugin folders with the application. Copy
        # them once into per-user storage; all subsequent operations use that
        # common location.
        if LEGACY_PLUGINS_DIR.is_dir():
            for source in LEGACY_PLUGINS_DIR.iterdir():
                if not source.is_dir() or source.name.startswith(("_", ".")):
                    continue
                if not (source / "plugin.json").is_file():
                    continue
                manifest = self._load_manifest(source)
                if manifest:
                    destination = USER_PLUGINS_DIR / manifest["id"]
                    if not destination.exists():
                        shutil.copytree(source, destination)
        self._ready = True

    def list_plugins(self) -> list[dict]:
        with self._lock:
            self._ensure_ready()
            plugins: list[dict] = []
            for directory in sorted(USER_PLUGINS_DIR.iterdir()):
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                manifest = self._load_manifest(directory)
                if manifest:
                    plugins.append({**manifest, "dir": str(directory)})
        runner_state = self._runner.snapshot()
        result = []
        for plugin in plugins:
            state = runner_state.get(plugin["id"], {})
            result.append({
                "id": plugin["id"],
                "name": plugin["name"],
                "version": plugin["version"],
                "description": plugin.get("description", ""),
                "repository": plugin.get("repository", ""),
                "host": plugin.get("host", {}),
                "config_schema": plugin.get("config_schema", []),
                "config_ui": plugin.get("config_ui", ""),
                "dir": plugin["dir"],
                "entry": plugin["entry"],
                "running": state.get("running", False),
                "status": state.get("status", "stopped"),
                "pid": state.get("pid"),
                "progress": state.get("progress"),
            })
        result.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        return result

    def get_plugin(self, plugin_id: str) -> dict:
        for plugin in self.list_plugins():
            if plugin["id"] == plugin_id:
                return plugin
        raise PluginError(f"插件不存在: {plugin_id}")

    def _load_manifest(self, plugin_dir: Path) -> dict | None:
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            return _validate_manifest(manifest, plugin_dir.name)
        except (json.JSONDecodeError, PluginError, OSError):
            return None

    def install(self, zip_path: str, *, replace: bool = False) -> dict:
        with self._lock:
            self._ensure_ready()
            work = USER_PLUGINS_DIR / f".tmp-install-{uuid.uuid4().hex}"
            work.mkdir(parents=True, exist_ok=False)
            backup: Path | None = None
            try:
                try:
                    with zipfile.ZipFile(zip_path) as archive:
                        infos = archive.infolist()
                        if len(infos) > MAX_ZIP_MEMBERS:
                            raise PluginError(f"插件包文件过多(上限 {MAX_ZIP_MEMBERS})")
                        if sum(info.file_size for info in infos) > MAX_ZIP_UNCOMPRESSED_BYTES:
                            raise PluginError("插件包解压后过大(上限 50 MB)")
                        for info in infos:
                            _check_zip_member(info.filename)
                        archive.extractall(work)
                    if (work / "plugin.json").exists():
                        source = work
                    else:
                        candidates = [
                            entry for entry in work.iterdir()
                            if entry.is_dir() and (entry / "plugin.json").exists()
                        ]
                        if not candidates:
                            raise PluginError("zip 中未找到 plugin.json")
                        if len(candidates) > 1:
                            raise PluginError("zip 中发现多个 plugin.json，无法确定插件根目录")
                        source = candidates[0]
                    manifest = self._load_manifest(source)
                    if not manifest:
                        raise PluginError("plugin.json 校验失败")
                    destination = USER_PLUGINS_DIR / manifest["id"]
                    if destination.exists() and not replace:
                        raise PluginError(f"插件 {manifest['id']} 已安装，请使用更新操作")
                    if self._runner.is_running(manifest["id"]):
                        raise PluginError("插件正在运行，请先停止")
                    if destination.exists():
                        backup = USER_PLUGINS_DIR / (
                            f".backup-{manifest['id']}-{uuid.uuid4().hex}")
                        shutil.move(str(destination), str(backup))
                    try:
                        shutil.move(str(source), str(destination))
                    except Exception:
                        if backup and backup.exists() and not destination.exists():
                            shutil.move(str(backup), str(destination))
                        raise
                    if backup:
                        shutil.rmtree(backup, ignore_errors=True)
                        backup = None
                    return {
                        "id": manifest["id"],
                        "name": manifest["name"],
                        "version": manifest["version"],
                        "updated": replace,
                    }
                except zipfile.BadZipFile as exc:
                    raise PluginError("不是有效的 zip 文件") from exc
            finally:
                shutil.rmtree(work, ignore_errors=True)
                if backup and backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)

    def uninstall(self, plugin_id: str) -> None:
        with self._lock:
            self._ensure_ready()
            _validate_plugin_id(plugin_id)
            directory = USER_PLUGINS_DIR / plugin_id
            if self._runner.is_running(plugin_id):
                raise PluginError("插件正在运行，请先停止")
            if not directory.exists():
                raise PluginError(f"插件不存在: {plugin_id}")
            shutil.rmtree(directory)

    def plugin_data_dir(self, plugin_id: str) -> Path:
        _validate_plugin_id(plugin_id)
        directory = PLUGIN_DATA_DIR / plugin_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory


def _check_zip_member(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise PluginError(f"zip 内含非法路径: {name}")
