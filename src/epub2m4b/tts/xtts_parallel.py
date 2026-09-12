from __future__ import annotations

import atexit
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .xtts import XTTSEngine

_ENGINE: XTTSEngine | None = None
_REFERENCE_WAV: Path | None = None
_WORKER_LOGS: list[str] = []


@dataclass(slots=True, frozen=True)
class XTTSPoolConfig:
    device: str
    accept_model_license: bool
    voice_mode: str
    speaker: str
    speed: float
    performance_mode: str
    reference_wav: str | None = None


def _capture_log(message: str) -> None:
    _WORKER_LOGS.append(str(message))


def _close_worker() -> None:
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.close()
        finally:
            _ENGINE = None


def init_xtts_worker(config: dict[str, Any]) -> None:
    """ProcessPool initializer: load one independent XTTS model per process."""

    global _ENGINE, _REFERENCE_WAV, _WORKER_LOGS
    _WORKER_LOGS = []
    _REFERENCE_WAV = Path(config["reference_wav"]) if config.get("reference_wav") else None
    _ENGINE = XTTSEngine(
        device=str(config["device"]),
        accept_model_license=bool(config["accept_model_license"]),
        voice_mode=str(config["voice_mode"]),
        speaker=str(config["speaker"]),
        speed=float(config["speed"]),
        performance_mode=str(config["performance_mode"]),
        log=_capture_log,
    )
    _ENGINE.load()
    atexit.register(_close_worker)


def _stable_seed(task_id: str, text: str) -> int:
    digest = hashlib.sha256(f"{task_id}\0{text}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") & 0x7FFFFFFF


def synthesize_xtts_task(task: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one chunk in an isolated worker process and atomically publish it."""

    if _ENGINE is None:
        raise RuntimeError("XTTS worker modeli yuklenmedi.")

    text = str(task["text"])
    output_path = Path(task["output_path"])
    task_id = str(task["task_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(f"{output_path.stem}.part.{os.getpid()}.wav")
    part_path.unlink(missing_ok=True)

    # Separate processes already isolate XTTS model state.  Stable per-chunk RNG
    # makes output independent of which worker receives a task.
    try:
        import torch

        seed = _stable_seed(task_id, text)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except Exception:
        pass

    started = time.perf_counter()
    try:
        artifact = _ENGINE.synthesize(text, part_path, _REFERENCE_WAV)
        os.replace(part_path, output_path)
    finally:
        part_path.unlink(missing_ok=True)
    synth_wall_seconds = time.perf_counter() - started

    global _WORKER_LOGS
    logs = list(_WORKER_LOGS)
    _WORKER_LOGS.clear()
    stats = _ENGINE.runtime_stats()
    return {
        "task_id": task_id,
        "duration_seconds": artifact.duration_seconds,
        "sample_rate": artifact.sample_rate,
        "synth_wall_seconds": synth_wall_seconds,
        "output_path": str(output_path),
        "worker_pid": os.getpid(),
        "worker_logs": logs,
        "runtime": stats,
        "effective_performance_mode": _ENGINE.effective_performance_mode,
    }
