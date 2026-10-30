"""GitHub release helpers shared by application and plugin updates."""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_USER_AGENT = "BNU-ToolBox-Updater"
_ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
}


class ReleaseError(RuntimeError):
    pass


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+){0,3})", str(value or ""))
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def compare_versions(left: str, right: str) -> int:
    left_parts, right_parts = version_tuple(left), version_tuple(right)
    width = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (width - len(left_parts))
    right_parts += (0,) * (width - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)


def minimum_host_satisfied(minimum: str, current: str) -> bool:
    return not minimum or compare_versions(current, minimum) >= 0


def require_https_github(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or ""))
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ReleaseError(f"不允许的下载地址: {url!r}")
    return urllib.parse.urlunparse(parsed)


def fetch_json(url: str, timeout: float = 15.0) -> Any:
    safe_url = require_https_github(url)
    request = urllib.request.Request(
        safe_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ReleaseError(f"下载 JSON 失败: HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ReleaseError(f"无法获取更新信息: {exc}") from exc


def download_file(
    url: str,
    destination: Path,
    *,
    expected_sha256: str = "",
    max_bytes: int = 250 * 1024 * 1024,
    timeout: float = 60.0,
) -> Path:
    safe_url = require_https_github(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(
        safe_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(
                temporary, "wb") as output:
            if response.status != 200:
                raise ReleaseError(f"下载失败: HTTP {response.status}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ReleaseError("下载文件超过允许大小")
                output.write(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        if expected_sha256 and actual.casefold() != expected_sha256.casefold():
            raise ReleaseError("文件校验失败，SHA-256 不匹配")
        temporary.replace(destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class GithubRelease:
    tag: str
    version: str
    name: str
    html_url: str
    published_at: str
    prerelease: bool
    assets: tuple[ReleaseAsset, ...]


def github_releases(repository: str) -> list[GithubRelease]:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ReleaseError("GitHub 仓库名格式错误")
    payload = fetch_json(
        f"https://api.github.com/repos/{repository}/releases?per_page=50")
    if not isinstance(payload, list):
        raise ReleaseError("GitHub Release 响应格式错误")
    releases: list[GithubRelease] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag = str(item.get("tag_name") or "")
        version_match = re.search(r"(\d+(?:\.\d+){1,3})", tag)
        if not version_match:
            continue
        assets = tuple(
            ReleaseAsset(
                name=str(asset.get("name") or ""),
                url=str(asset.get("browser_download_url") or ""),
                size=int(asset.get("size") or 0),
            )
            for asset in item.get("assets", [])
            if isinstance(asset, dict)
        )
        releases.append(GithubRelease(
            tag=tag,
            version=version_match.group(1),
            name=str(item.get("name") or tag),
            html_url=str(item.get("html_url") or ""),
            published_at=str(item.get("published_at") or ""),
            prerelease=bool(item.get("prerelease")),
            assets=assets,
        ))
    releases.sort(key=lambda release: version_tuple(release.version), reverse=True)
    return releases
