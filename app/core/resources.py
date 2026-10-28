"""Host resource detection and conservative browser-concurrency guidance."""
from __future__ import annotations

import ctypes
import math
import os
from dataclasses import asdict, dataclass

_MB_PER_BROWSER = 550
_MAX_RECOMMENDED_WORKERS = 12


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessorRelationship(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_ubyte),
        ("EfficiencyClass", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte * 6),
    ]


class _GroupAffinity(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_size_t),
        ("Group", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort * 3),
    ]


class _ProcessorCoreInfo(ctypes.Structure):
    _fields_ = [
        ("Relationship", ctypes.c_ulong),
        ("Size", ctypes.c_ulong),
        ("Processor", _ProcessorRelationship),
        ("GroupMask", _GroupAffinity),
    ]


@dataclass(frozen=True)
class ResourceProfile:
    total_memory_gb: float
    physical_cores: int
    logical_processors: int
    recommended_workers: int
    warning_threshold: int
    estimated_mb_per_browser: int
    formula: str

    def to_dict(self) -> dict:
        return asdict(self)


def _total_memory_bytes() -> int:
    if os.name != "nt":
        return 0
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)):
            return 0
    except (AttributeError, OSError):
        return 0
    return int(status.ullTotalPhys)


def _physical_core_count() -> int:
    if os.name != "nt":
        return max(1, (os.cpu_count() or 2) // 2)
    try:
        get_info = ctypes.windll.kernel32.GetLogicalProcessorInformationEx
        relation_processor_core = 0
        length = ctypes.c_ulong(0)
        get_info(relation_processor_core, None, ctypes.byref(length))
        if not length.value:
            raise OSError("empty processor information")
        buffer = ctypes.create_string_buffer(length.value)
        if not get_info(
                relation_processor_core, buffer, ctypes.byref(length)):
            raise OSError("GetLogicalProcessorInformationEx failed")
        offset = 0
        count = 0
        while offset + 8 <= length.value:
            row = _ProcessorCoreInfo.from_buffer(buffer, offset)
            size = int(row.Size)
            if size <= 0 or offset + size > length.value:
                break
            if int(row.Relationship) == relation_processor_core:
                count += 1
            offset += size
        if count:
            return count
    except (AttributeError, OSError, ValueError):
        pass
    # Divided-logical-core fallback errs deliberately on the conservative side.
    return max(1, (os.cpu_count() or 2) // 2)


def resource_profile() -> ResourceProfile:
    """Return a concurrency default sized for headless video browsers.

    The stress baseline on a 10-core / 32 GB Windows 11 laptop averaged about
    420 MB working set per 1080p browser. A 550 MB allowance leaves room for
    player buffers, network traffic and snapshot spikes. CPU capacity is capped
    at 80% of physical cores so the desktop remains responsive during 3x video.
    """
    total_bytes = _total_memory_bytes()
    total_gb = total_bytes / (1024 ** 3) if total_bytes else 0.0
    physical = _physical_core_count()
    logical = max(1, os.cpu_count() or physical)
    if total_gb:
        reserved_gb = max(4.0, total_gb * 0.15)
        usable_mb = max(0.0, total_gb - reserved_gb) * 1024 * 0.70
        memory_workers = max(1, math.floor(usable_mb / _MB_PER_BROWSER))
    else:
        memory_workers = _MAX_RECOMMENDED_WORKERS
    cpu_workers = max(1, math.floor(physical * 0.8))
    recommended = max(
        1,
        min(_MAX_RECOMMENDED_WORKERS, memory_workers, cpu_workers),
    )
    return ResourceProfile(
        total_memory_gb=round(total_gb, 1),
        physical_cores=physical,
        logical_processors=logical,
        recommended_workers=recommended,
        warning_threshold=recommended * 2,
        estimated_mb_per_browser=_MB_PER_BROWSER,
        formula=(
            "min(12, 0.8×物理核心数, 70%可用内存÷550MB)，"
            "预留至少4GB系统内存"
        ),
    )


def recommended_worker_count() -> int:
    return resource_profile().recommended_workers
