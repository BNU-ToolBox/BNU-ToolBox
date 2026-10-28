"""Microsoft Edge discovery and automatic Edge WebDriver management."""
from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

import requests

from .paths import RUNTIME_DIR

EDGE_DRIVER_DIR = RUNTIME_DIR / "msedgedriver"
EDGE_DRIVER_DOWNLOAD_BASE = "https://msedgedriver.microsoft.com"
EDGE_DRIVER_FALLBACK_BASE = "https://msedgedriver.azureedge.net"
_LOCK = threading.Lock()


def _file_version(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(
            str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(
                str(path), 0, size, buffer):
            return ""

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not ctypes.windll.version.VerQueryValueW(
                buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(FixedFileInfo)).contents
        return "{}.{}.{}.{}".format(
            info.dwFileVersionMS >> 16,
            info.dwFileVersionMS & 0xFFFF,
            info.dwFileVersionLS >> 16,
            info.dwFileVersionLS & 0xFFFF,
        )
    except (AttributeError, OSError, ValueError):
        return ""


def find_edge_executable() -> Path | None:
    if os.name != "nt":
        return None
    import winreg

    registry_paths = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
    )
    for hive, key_path in registry_paths:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value = winreg.QueryValue(key, None)
            path = Path(str(value).strip('"'))
            if path.is_file():
                return path
        except OSError:
            continue
    for raw in (
        os.path.expandvars(
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ):
        path = Path(raw)
        if path.is_file():
            return path
    return None


def edge_status() -> dict:
    executable = find_edge_executable()
    edge_version = _file_version(executable) if executable else ""
    cached = sorted(
        EDGE_DRIVER_DIR.glob("*/msedgedriver.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if EDGE_DRIVER_DIR.exists() else []
    driver = cached[0] if cached else None
    driver_version = _file_version(driver) if driver else ""
    compatible = bool(
        edge_version and driver_version
        and edge_version.split(".")[0] == driver_version.split(".")[0])
    exact = bool(edge_version and driver_version
                 and edge_version == driver_version)
    return {
        "edge_path": str(executable or ""),
        "edge_version": edge_version,
        "driver_path": str(driver or ""),
        "driver_version": driver_version,
        "compatible": compatible,
        "exact_match": exact,
    }


def _download_urls(version: str) -> list[str]:
    major = version.split(".", 1)[0]
    urls = []
    for base in (
        EDGE_DRIVER_DOWNLOAD_BASE,
        EDGE_DRIVER_FALLBACK_BASE,
    ):
        urls.append(f"{base}/{version}/edgedriver_win64.zip")
    for base in (
        EDGE_DRIVER_DOWNLOAD_BASE,
        EDGE_DRIVER_FALLBACK_BASE,
    ):
        try:
            response = requests.get(
                f"{base}/LATEST_RELEASE_{major}", timeout=15)
            if response.ok:
                latest = response.text.strip()
                if latest:
                    urls.append(f"{base}/{latest}/edgedriver_win64.zip")
        except requests.RequestException:
            continue
    return list(dict.fromkeys(urls))


def _download_driver(version: str, log=None) -> Path:
    target_dir = EDGE_DRIVER_DIR / version
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "msedgedriver.exe"
    last_error = ""
    for url in _download_urls(version):
        if log:
            log(f"正在下载 EdgeDriver: {url}")
        temp_zip = ""
        try:
            response = requests.get(url, timeout=60, stream=True)
            if response.status_code == 404:
                last_error = f"未找到版本 {version}"
                continue
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".zip") as handle:
                temp_zip = handle.name
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
            with zipfile.ZipFile(temp_zip) as archive:
                member = next((
                    item for item in archive.infolist()
                    if Path(item.filename).name.lower() == "msedgedriver.exe"
                ), None)
                if member is None:
                    raise RuntimeError("下载包中未找到 msedgedriver.exe")
                with archive.open(member) as source:
                    with tempfile.NamedTemporaryFile(
                            dir=target_dir, prefix=".driver-",
                            suffix=".tmp", delete=False) as output:
                        temp_driver = Path(output.name)
                        shutil.copyfileobj(source, output)
            os.replace(temp_driver, target)
            return target
        except (requests.RequestException, OSError, RuntimeError,
                zipfile.BadZipFile) as exc:
            last_error = str(exc)
            try:
                if "temp_driver" in locals():
                    temp_driver.unlink(missing_ok=True)
            except OSError:
                pass
        finally:
            if temp_zip:
                try:
                    Path(temp_zip).unlink(missing_ok=True)
                except OSError:
                    pass
    raise RuntimeError(f"EdgeDriver 下载失败: {last_error or '未知错误'}")


def ensure_edge_driver(log=None, force: bool = False) -> Path:
    executable = find_edge_executable()
    if executable is None:
        raise RuntimeError("未检测到 Microsoft Edge，请确认 Windows 11 已安装 Edge")
    edge_version = _file_version(executable)
    if not edge_version:
        raise RuntimeError("无法读取 Microsoft Edge 版本")
    with _LOCK:
        status = edge_status()
        driver = Path(status["driver_path"]) if status["driver_path"] else None
        if not force and status["exact_match"] and driver and driver.is_file():
            return driver
        driver = _download_driver(edge_version, log=log)
        driver_version = _file_version(driver)
        if driver_version.split(".")[0] != edge_version.split(".")[0]:
            raise RuntimeError(
                f"EdgeDriver 主版本不匹配: Edge {edge_version}, "
                f"Driver {driver_version or 'unknown'}")
        if log:
            log(f"EdgeDriver 已更新: {driver_version}")
        return driver
