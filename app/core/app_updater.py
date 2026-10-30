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
        }

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
            candidates: list[tuple[GithubRelease, str]] = []
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
                    candidates.append((release, installer.url))
            if not candidates:
                raise ReleaseError("没有找到可用的安装包")
            release, installer_url = candidates[0]
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
                    _installer_url=installer_url,
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
            installer_url = self._state.get("_installer_url")
            if not isinstance(release, GithubRelease) or not installer_url:
                raise ReleaseError("请先检查更新")
            self._state.update(status="downloading", message="正在下载安装包")
        installer_name = installer_url.rsplit("/", 1)[-1]
        destination = UPDATE_DIR / installer_name
        expected_sha = ""
        checksum_asset = next(
            (asset for asset in release.assets if asset.name == "SHA256SUMS.txt"),
            None,
        )
        if checksum_asset:
            checksums = UPDATE_DIR / f"{release.version}-SHA256SUMS.txt"
            download_file(checksum_asset.url, checksums, max_bytes=1024 * 1024)
            for line in checksums.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == installer_name:
                    expected_sha = parts[0]
                    break
            checksums.unlink(missing_ok=True)
        try:
            download_file(
                installer_url,
                destination,
                expected_sha256=expected_sha,
                max_bytes=250 * 1024 * 1024,
            )
        except Exception as exc:
            with self._lock:
                self._state.update(status="error", message=f"下载安装包失败: {exc}")
            raise
        helper = self._write_update_helper(destination)
        flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
            if os.name == "nt" else 0
        )
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
                "-ExecutionPolicy", "Bypass", "-File", str(helper),
            ],
            close_fds=True,
            creationflags=flags,
        )
        with self._lock:
            self._state.update(
                status="installing",
                message="安装程序已启动，应用即将重启",
            )
        return self.snapshot()

    def _write_update_helper(self, installer: Path) -> Path:
        root = Path(__file__).resolve().parents[2]
        pythonw = Path(sys.executable)
        if pythonw.name.casefold() == "python.exe":
            candidate = pythonw.with_name("pythonw.exe")
            if candidate.is_file():
                pythonw = candidate
        helper = Path(tempfile.gettempdir()) / f"BNU-ToolBox-update-{os.getpid()}.ps1"

        def quote(value: object) -> str:
            return "'" + str(value).replace("'", "''") + "'"

        helper.write_text(
            "$ErrorActionPreference = 'SilentlyContinue'\n"
            "Start-Sleep -Seconds 3\n"
            f"$installer = {quote(installer)}\n"
            f"$app = {quote(pythonw)}\n"
            f"$root = {quote(root)}\n"
            f"$main = {quote(root / 'app' / 'main.py')}\n"
            "$process = Start-Process -FilePath $installer "
            "-ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"
            "'/CLOSEAPPLICATIONS','/FORCECLOSEAPPLICATIONS') "
            "-Verb RunAs -PassThru\n"
            "$process.WaitForExit()\n"
            "if ($process.ExitCode -eq 0) {\n"
            "  Start-Process -FilePath $app -ArgumentList @($main) "
            "-WorkingDirectory $root\n"
            "}\n",
            encoding="utf-8-sig",
        )
        return helper


app_updater = AppUpdater()
