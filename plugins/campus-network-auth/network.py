"""Windows 11 network adapter detection for campus authentication."""
from __future__ import annotations

import json
import os
import platform
import subprocess


def _run(command: list[str], timeout: float = 10.0) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        timeout=timeout,
        check=False,
    )
    return result.stdout or ""


def _classify(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in (
            "802.11", "wi-fi", "wifi", "wireless", "wlan", "无线")):
        return "wifi"
    if any(marker in lowered for marker in (
            "802.3", "ethernet", "以太网", "乙太網路")):
        return "ethernet"
    return ""


def detect_connection() -> dict:
    if platform.system().lower() != "windows":
        return {
            "ethernet": False,
            "wifi": False,
            "interfaces": [],
            "error": "BNU-ToolBox currently supports Windows 11 only",
        }
    interfaces: list[dict] = []
    script = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
        "Get-NetAdapter -Physical -ErrorAction SilentlyContinue | "
        "Where-Object {$_.Status -eq 'Up'} | "
        "Select-Object Name,InterfaceDescription,PhysicalMediaType | "
        "ConvertTo-Json -Compress"
    )
    try:
        output = _run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script
        ]).strip()
        if output:
            value = json.loads(output)
            rows = value if isinstance(value, list) else [value]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = " ".join(str(row.get(key) or "") for key in (
                    "Name", "InterfaceDescription", "PhysicalMediaType"))
                kind = _classify(text)
                if kind:
                    interfaces.append({
                        "name": str(row.get("Name") or ""),
                        "kind": kind,
                    })
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {
        "ethernet": any(item["kind"] == "ethernet" for item in interfaces),
        "wifi": any(item["kind"] == "wifi" for item in interfaces),
        "interfaces": interfaces,
    }


def select_portal(config: dict) -> tuple[str, str]:
    wired = str(config.get("wired_portal") or "").strip()
    wireless = str(config.get("wireless_portal") or "").strip()
    mode = str(config.get("connection_mode") or "auto").strip().lower()
    detected = detect_connection()
    if mode == "wired":
        return wired or wireless, "wired"
    if mode == "wireless":
        return wireless or wired, "wireless"
    if detected.get("ethernet") and wired:
        return wired, "wired"
    if detected.get("wifi") and wireless:
        return wireless, "wireless"
    if wired:
        return wired, "wired"
    if wireless:
        return wireless, "wireless"
    return "", "unknown"
