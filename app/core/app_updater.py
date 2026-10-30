"""Application release discovery and self-update launch."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .paths import UPDATE_DIR
from .release_utils import (
    GithubRelease,
    ReleaseAsset,
    ReleaseError,
    compare_versions,
    download_file,
    github_releases,
)
from ..version import __version__

APP_REPOSITORY = "BNU-ToolBox/BNU-ToolBox"


class AppUpdater:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict = {
            "status": "idle",
            "current_version": __version__,
            "latest_version": "",
            "available": False,
            "release_url": "",
            "message": "",
            "checked_at": "",
            "waiting_for_elevation": False,
        }
        self._status_path: Path | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                key: value for key, value in self._state.items()
                if not key.startswith("_")
            }

    def check(self) -> dict:
        with self._lock:
            self._state.update(status="checking", message="正在检查主程序更新")
        try:
            releases = github_releases(APP_REPOSITORY)
            candidates: list[tuple[GithubRelease, ReleaseAsset]] = []
            for release in releases:
                installer = next(
                    (
                        asset for asset in release.assets
                        if re.fullmatch(
                            r"BNU-ToolBox-Setup-\d+\.\d+\.\d+\.exe",
                            asset.name,
                        )
                    ),
                    None,
                )
                if installer:
                    candidates.append((release, installer))
            if not candidates:
                raise ReleaseError("没有找到可用的安装包")
            release, installer = candidates[0]
            available = compare_versions(release.version, __version__) > 0
            with self._lock:
                self._state.update(
                    status="available" if available else "up_to_date",
                    latest_version=release.version,
                    available=available,
                    release_url=release.html_url,
                    message=(
                        f"发现新版本 {release.version}"
                        if available else "当前已是最新版本"
                    ),
                    checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    _release=release,
                    _installer=installer,
                    _installer_url=installer.url,
                )
            return self.snapshot()
        except ReleaseError as exc:
            with self._lock:
                self._state.update(
                    status="error",
                    available=False,
                    message=str(exc),
                    checked_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            return self.snapshot()

    def download_and_launch(self) -> dict:
        with self._lock:
            release = self._state.get("_release")
            installer = self._state.get("_installer")
            if not isinstance(release, GithubRelease) or not isinstance(
                    installer, ReleaseAsset):
                raise ReleaseError("请先检查更新")
            if self._state.get("status") in {
                    "downloading", "waiting_for_elevation", "installing"}:
                raise ReleaseError("更新任务已经开始，请等待当前操作完成")
            self._state.update(status="downloading", message="正在下载安装包")
        installer_name = installer.name
        destination = UPDATE_DIR / installer_name
        expected_sha = ""
        checksum_asset = next(
            (asset for asset in release.assets if asset.name == "SHA256SUMS.txt"),
            None,
        )
        if checksum_asset:
            checksums = UPDATE_DIR / f"{release.version}-SHA256SUMS.txt"
            download_file(
                checksum_asset.url,
                checksums,
                max_bytes=1024 * 1024,
                accept="application/octet-stream",
            )
            for line in checksums.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == installer_name:
                    expected_sha = parts[0]
                    break
            checksums.unlink(missing_ok=True)
        try:
            download_file(
                installer.url,
                destination,
                expected_sha256=expected_sha,
                max_bytes=250 * 1024 * 1024,
                accept="application/octet-stream",
            )
        except Exception as exc:
            with self._lock:
                self._state.update(status="error", message=f"下载安装包失败: {exc}")
            raise
        self._status_path = UPDATE_DIR / (
            f"update-{release.version}-{os.getpid()}-status.json")
        self._status_path.unlink(missing_ok=True)
        helper = self._write_update_helper(destination, self._status_path)
        flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            if os.name == "nt" else 0
        )
        try:
            subprocess.Popen(
                [
                    "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
                    "-ExecutionPolicy", "Bypass", "-File", str(helper),
                ],
                close_fds=True,
                creationflags=flags,
            )
        except Exception as exc:
            with self._lock:
                self._state.update(
                    status="error", message=f"无法启动更新助手: {exc}")
            raise
        with self._lock:
            self._state.update(
                status="waiting_for_elevation",
                message="等待 Windows 管理员授权，授权后将自动安装并重启",
                waiting_for_elevation=True,
            )
        return self.snapshot()

    def pending_status_path(self) -> Path | None:
        with self._lock:
            return self._status_path

    def mark_helper_failed(self, message: str) -> None:
        with self._lock:
            self._state.update(
                status="error",
                message=f"更新未完成: {message}",
                waiting_for_elevation=False,
            )

    def mark_installing(self) -> None:
        with self._lock:
            self._state.update(
                status="installing",
                message="管理员授权已通过，正在安装更新",
                waiting_for_elevation=False,
            )

    def _write_update_helper(
        self, installer: Path, status_path: Path) -> Path:
        root = Path(__file__).resolve().parents[2]
        pythonw = Path(sys.executable)
        if pythonw.name.casefold() == "python.exe":
            candidate = pythonw.with_name("pythonw.exe")
            if candidate.is_file():
                pythonw = candidate
        helper = Path(tempfile.gettempdir()) / f"BNU-ToolBox-update-{os.getpid()}.ps1"
        log_path = UPDATE_DIR / "update.log"

        def quote(value: object) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        helper.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f"$installer = {quote(installer)}\n"
            f"$app = {quote(pythonw)}\n"
            f"$root = {quote(root)}\n"
            f"$main = {quote(root / 'app' / 'main.py')}\n"
            f"$status = {quote(status_path)}\n"
            f"$log = {quote(log_path)}\n"
            "function Write-Status([string]$State, [string]$Message) {\n"
            "  @{status=$State; message=$Message; time=(Get-Date).ToString('o')} |\n"
            "    ConvertTo-Json -Compress | Set-Content -LiteralPath $status -Encoding UTF8\n"
            "  Add-Content -LiteralPath $log -Encoding UTF8 "
            "-Value \"$(Get-Date -Format o) [$State] $Message\"\n"
            "}\n"
            "try {\n"
            "  Write-Status 'waiting' '等待管理员授权'\n"
            "  $process = Start-Process -FilePath $installer "
            "-ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"
            "'/CLOSEAPPLICATIONS','/FORCECLOSEAPPLICATIONS') "
            "-Verb RunAs -PassThru\n"
            "  Write-Status 'launched' '安装程序已启动'\n"
            "  $process.WaitForExit()\n"
            "  if ($process.ExitCode -ne 0) { "
            "throw \"安装程序退出代码 $($process.ExitCode)\" }\n"
            "  Write-Status 'completed' '安装完成'\n"
            "  Start-Process -FilePath $app -ArgumentList @($main) "
            "-WorkingDirectory $root\n"
            "} catch {\n"
            "  Write-Status 'failed' $_.Exception.Message\n"
            "}\n",
            encoding="utf-8-sig",
        )
        return helper


app_updater = AppUpdater()
