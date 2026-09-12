from __future__ import annotations

import csv
import io
import subprocess
import time
from typing import Any

_NVML_HANDLE = None
_NVML_INDEX = None
_LAST_STATS: dict[str, Any] = {}
_LAST_AT = 0.0


def _device_index(device: str) -> int:
    if ":" in str(device):
        try:
            return int(str(device).split(":", 1)[1])
        except ValueError:
            return 0
    return 0


def _nvidia_smi_stats(index: int) -> dict[str, Any]:
    """Fallback telemetry when nvidia-ml-py is absent or cannot initialize."""

    query = "name,utilization.gpu,power.draw,memory.used,memory.total"
    command = [
        "nvidia-smi",
        f"--id={index}",
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=3, check=True)
    row = next(csv.reader(io.StringIO(completed.stdout.strip())))
    if len(row) < 5:
        raise RuntimeError("nvidia-smi telemetri satiri eksik")
    name, util, power, used_mib, total_mib = [value.strip() for value in row[:5]]
    return {
        "gpu_name": name,
        "gpu_util_percent": int(float(util)),
        "power_w": round(float(power)),
        "vram_device_used_gb": round(float(used_mib) / 1024.0, 2),
        "vram_device_total_gb": round(float(total_mib) / 1024.0, 2),
        "vram_total_gb": round(float(total_mib) / 1024.0, 2),
        "telemetry_source": "nvidia-smi",
    }


def nvidia_runtime_stats(device: str = "cuda", min_interval: float = 0.5) -> dict[str, Any]:
    """Return device-wide NVIDIA telemetry without importing/loading a TTS model.

    Prefer NVML.  If the optional Python binding is missing, fall back to the
    NVIDIA driver utility that is normally present whenever CUDA works.  This
    avoids presenting PyTorch's process-local ``memory_allocated`` as if it were
    whole-device VRAM usage.
    """

    global _NVML_HANDLE, _NVML_INDEX, _LAST_STATS, _LAST_AT
    if not str(device).startswith("cuda"):
        return {"device": device}
    now = time.monotonic()
    effective_interval = min_interval
    if _LAST_STATS.get("telemetry_source") == "nvidia-smi":
        # Launching nvidia-smi is much heavier than an NVML call. Sampling it
        # four times per second would steal CPU time from TTS scheduling, so
        # cap the fallback to at most once per second.
        effective_interval = max(effective_interval, 1.0)
    if _LAST_STATS and now - _LAST_AT < effective_interval:
        return dict(_LAST_STATS)
    stats: dict[str, Any] = {"device": device}
    index = _device_index(device)
    try:
        import pynvml

        if _NVML_HANDLE is None or _NVML_INDEX != index:
            pynvml.nvmlInit()
            _NVML_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(index)
            _NVML_INDEX = index
        handle = _NVML_HANDLE
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        stats["gpu_name"] = str(name)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        stats["gpu_util_percent"] = int(util.gpu)
        stats["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        stats["vram_device_used_gb"] = round(memory.used / (1024**3), 2)
        stats["vram_device_total_gb"] = round(memory.total / (1024**3), 2)
        stats["vram_total_gb"] = stats["vram_device_total_gb"]
        stats["telemetry_source"] = "nvml"
    except Exception:
        try:
            stats.update(_nvidia_smi_stats(index))
        except Exception:
            try:
                import torch

                if torch.cuda.is_available():
                    stats["gpu_name"] = torch.cuda.get_device_name(index)
                    stats["vram_total_gb"] = round(
                        torch.cuda.get_device_properties(index).total_memory / (1024**3), 2
                    )
                    stats["telemetry_source"] = "torch"
            except Exception:
                pass
    _LAST_STATS = stats
    _LAST_AT = now
    return dict(stats)
