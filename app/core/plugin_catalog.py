"""Online plugin registry and release-metadata resolution."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .paths import CACHE_DIR, UPDATE_DIR
from .plugin_manager import PluginError, PluginManager
from .release_utils import (
    ReleaseError,
    compare_versions,
    download_file,
    fetch_github_content,
    fetch_json,
    github_release_asset_url,
    minimum_host_satisfied,
    require_https_github,
    version_tuple,
)
from ..version import __version__

PLUGIN_INDEX_URLS = (
    "https://cdn.jsdelivr.net/gh/BNU-ToolBox/"
    "BNUToolboxPlugins@main/plugins.json",
    "https://raw.githubusercontent.com/BNU-ToolBox/"
    "BNUToolboxPlugins/main/plugins.json",
)


class PluginCatalog:
    def __init__(self, manager: PluginManager):
        self.manager = manager
        self._lock = threading.Lock()
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_at = 0.0
        self._cache_path = CACHE_DIR / "plugin-catalog.json"

    def list_catalog(self, *, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if (
                not force
                and self._snapshot is not None
                and time.time() - self._snapshot_at < 300
            ):
                snapshot = self._snapshot
            else:
                snapshot = None
        if snapshot is not None:
            return self._with_installed(snapshot, stale=False)
        try:
            index = self._fetch_index()
            entries = self._validate_index(index)
            resolved = self._resolve_entries(entries)
            snapshot = {
                "schema_version": 1,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "plugins": resolved,
            }
            self._save_cache(snapshot)
            with self._lock:
                self._snapshot = snapshot
                self._snapshot_at = time.time()
            return self._with_installed(snapshot, stale=False)
        except ReleaseError as exc:
            cached = self._load_cache()
            if cached is not None:
                return self._with_installed(cached, stale=True, error=str(exc))
            raise

    @staticmethod
    def _fetch_index() -> Any:
        last_error: ReleaseError | None = None
        try:
            return fetch_github_content(
                "BNU-ToolBox/BNUToolboxPlugins",
                "plugins.json",
                ref="main",
                timeout=8.0,
            )
        except ReleaseError as exc:
            last_error = exc
        for url in PLUGIN_INDEX_URLS:
            try:
                return fetch_json(url, timeout=5.0)
            except ReleaseError as exc:
                last_error = exc
        raise last_error or ReleaseError("无法获取插件索引")

    def _validate_index(self, payload: Any) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("plugins"), list):
            raise ReleaseError("插件索引格式错误")
        entries: list[dict] = []
        seen: set[str] = set()
        for raw in payload["plugins"]:
            if not isinstance(raw, dict):
                continue
            plugin_id = str(raw.get("id") or "").strip()
            metadata_url = str(raw.get("metadata_url") or "").strip()
            if not plugin_id or plugin_id in seen or not metadata_url:
                continue
            require_https_github(metadata_url)
            seen.add(plugin_id)
            entries.append(raw)
        if not entries:
            raise ReleaseError("插件索引中没有有效插件")
        return entries

    def _resolve_entries(self, entries: list[dict]) -> list[dict]:
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(8, len(entries))) as executor:
            futures = {
                executor.submit(self._resolve_entry, entry): entry
                for entry in entries
            }
            for future in as_completed(futures):
                entry = futures[future]
                try:
                    results.append(future.result())
                except ReleaseError as exc:
                    results.append({
                        "id": str(entry.get("id") or ""),
                        "name": str(entry.get("name") or entry.get("id") or ""),
                        "description": str(entry.get("description") or ""),
                        "repository": str(entry.get("repository") or ""),
                        "metadata_url": str(entry.get("metadata_url") or ""),
                        "error": str(exc),
                        "versions": [],
                        "latest": None,
                    })
        results.sort(key=lambda item: item["name"].casefold())
        return results

    def _resolve_entry(self, entry: dict) -> dict:
        embedded = entry.get("versions")
        metadata = (
            {**entry, "versions": embedded}
            if isinstance(embedded, list)
            else fetch_json(str(entry["metadata_url"]), timeout=8.0)
        )
        if not isinstance(metadata, dict):
            raise ReleaseError("插件版本元数据格式错误")
        plugin_id = str(metadata.get("plugin_id") or entry.get("id") or "")
        if plugin_id != str(entry.get("id") or ""):
            raise ReleaseError("插件索引与版本元数据 ID 不一致")
        versions = metadata.get("versions")
        if not isinstance(versions, list):
            raise ReleaseError("插件版本列表格式错误")
        valid_versions: list[dict] = []
        for version in versions:
            if not isinstance(version, dict) or not version.get("version"):
                continue
            download_url = str(version.get("download_url") or "")
            if download_url:
                try:
                    require_https_github(download_url)
                except ReleaseError:
                    continue
            valid_versions.append(version)
        valid_versions.sort(
            key=lambda item: version_tuple(str(item["version"])),
            reverse=True,
        )
        return {
            "id": plugin_id,
            "name": str(entry.get("name") or metadata.get("name") or plugin_id),
            "description": str(
                entry.get("description") or metadata.get("description") or ""),
            "repository": str(
                entry.get("repository") or metadata.get("repository") or ""),
            "metadata_url": str(entry["metadata_url"]),
            "latest": valid_versions[0] if valid_versions else None,
            "versions": valid_versions,
            "error": "",
        }

    def _with_installed(
        self, snapshot: dict, *, stale: bool, error: str = "",
    ) -> dict[str, Any]:
        installed = {plugin["id"]: plugin for plugin in self.manager.list_plugins()}
        plugins: list[dict] = []
        catalog_ids: set[str] = set()
        for item in snapshot.get("plugins", []):
            plugin_id = str(item.get("id") or "")
            catalog_ids.add(plugin_id)
            latest = item.get("latest") if isinstance(item.get("latest"), dict) else None
            installed_plugin = installed.get(plugin_id)
            installed_version = (
                str(installed_plugin.get("version") or "") if installed_plugin else "")
            latest_version = str(latest.get("version") or "") if latest else ""
            host = latest.get("host_version", {}) if latest else {}
            minimum = str(host.get("min") or "") if isinstance(host, dict) else ""
            maximum = str(host.get("max") or "") if isinstance(host, dict) else ""
            compatible = (
                minimum_host_satisfied(minimum, __version__)
                and (not maximum or compare_versions(__version__, maximum) <= 0)
            )
            update_available = bool(
                installed_plugin and latest and compatible
                and compare_versions(latest_version, installed_version) > 0
            )
            plugins.append({
                **item,
                "installed": bool(installed_plugin),
                "installed_version": installed_version,
                "running": bool(installed_plugin and installed_plugin.get("running")),
                "status": (
                    installed_plugin.get("status") if installed_plugin else "not-installed"),
                "update_available": update_available,
                "compatible": compatible,
                "dependency": minimum,
            })
        for plugin_id, plugin in installed.items():
            if plugin_id in catalog_ids:
                continue
            plugins.append({
                "id": plugin_id,
                "name": plugin["name"],
                "description": plugin.get("description", ""),
                "repository": plugin.get("repository", ""),
                "latest": None,
                "versions": [],
                "installed": True,
                "installed_version": plugin["version"],
                "running": plugin.get("running", False),
                "status": plugin.get("status", "stopped"),
                "update_available": False,
                "compatible": True,
                "dependency": (
                    plugin.get("host", {}).get("min_version", "")
                    if isinstance(plugin.get("host"), dict) else ""),
                "error": "",
                "local_only": True,
            })
        return {
            "plugins": plugins,
            "stale": stale,
            "error": error,
            "updated_at": snapshot.get("updated_at", ""),
            "host_version": __version__,
        }

    def install(
        self,
        plugin_id: str,
        *,
        update: bool = False,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict:
        catalog = self.list_catalog(force=True)
        item = next(
            (plugin for plugin in catalog["plugins"] if plugin["id"] == plugin_id),
            None,
        )
        if not item:
            raise PluginError(f"插件不存在于在线索引: {plugin_id}")
        if not item.get("compatible", False):
            raise PluginError(f"该插件需要更高版本的 BNU-ToolBox ({item['dependency']}+)")
        latest = item.get("latest")
        if not isinstance(latest, dict):
            raise PluginError("该插件没有可用版本")
        if item.get("installed") and not update:
            raise PluginError("插件已安装")
        if update and not item.get("update_available"):
            raise PluginError("插件已是最新版本")
        if item.get("running"):
            raise PluginError("插件正在运行，请先停止")
        download_url = str(latest.get("download_url") or "")
        repository = str(item.get("repository") or "")
        repository_slug = urllib.parse.urlparse(repository).path.strip("/")
        asset_name = download_url.rsplit("/", 1)[-1]
        try:
            download_url = github_release_asset_url(
                repository_slug,
                str(latest.get("release_tag") or ""),
                asset_name,
            )
        except ReleaseError:
            # Keep compatibility with mirrors that do not expose a Release
            # asset API; the browser URL remains a valid fallback.
            pass
        archive = UPDATE_DIR / "plugins" / f"{plugin_id}-{uuid.uuid4().hex}.zip"
        try:
            download_file(
                download_url,
                archive,
                expected_sha256=str(latest.get("sha256") or ""),
                max_bytes=50 * 1024 * 1024,
                progress_callback=progress,
                accept="application/octet-stream",
            )
            result = self.manager.install(str(archive), replace=update)
            with self._lock:
                self._snapshot = None
            return result
        finally:
            archive.unlink(missing_ok=True)

    def auto_update_installed(self) -> list[dict]:
        catalog = self.list_catalog(force=True)
        updated: list[dict] = []
        for item in catalog["plugins"]:
            if not item.get("update_available"):
                continue
            try:
                updated.append(self.install(item["id"], update=True))
            except (PluginError, ReleaseError):
                continue
        return updated

    def _load_cache(self) -> dict | None:
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _save_cache(self, snapshot: dict) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._cache_path)
