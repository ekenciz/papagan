from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, TextIO

from .xtts import XTTSEngine

_PROTOCOL_OUT: TextIO | None = None
_ENGINE: XTTSEngine | None = None
_REFERENCE_WAV: Path | None = None
_WORKER_LOGS: list[str] = []


def _emit(payload: dict[str, Any]) -> None:
    if _PROTOCOL_OUT is None:
        return
    _PROTOCOL_OUT.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    _PROTOCOL_OUT.flush()


def _capture_log(message: str) -> None:
    _WORKER_LOGS.append(str(message))


def _drain_logs() -> list[str]:
    logs = list(_WORKER_LOGS)
    _WORKER_LOGS.clear()
    return logs


def _stable_seed(task_id: str, text: str) -> int:
    digest = hashlib.sha256(f"{task_id}\0{text}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") & 0x7FFFFFFF


def _configure_engine(config: dict[str, Any]) -> None:
    global _ENGINE, _REFERENCE_WAV
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


def _synthesize(task: dict[str, Any]) -> dict[str, Any]:
    if _ENGINE is None:
        raise RuntimeError("XTTS worker modeli yuklenmedi.")

    text = str(task["text"])
    output_path = Path(task["output_path"])
    task_id = str(task["task_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(f"{output_path.stem}.part.{os.getpid()}.wav")
    part_path.unlink(missing_ok=True)

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
    wall = time.perf_counter() - started

    return {
        "type": "result",
        "task_id": task_id,
        "duration_seconds": artifact.duration_seconds,
        "sample_rate": artifact.sample_rate,
        "synth_wall_seconds": wall,
        "output_path": str(output_path),
        "worker_pid": os.getpid(),
        "worker_logs": _drain_logs(),
        "runtime": _ENGINE.runtime_stats(),
        "effective_performance_mode": _ENGINE.effective_performance_mode,
    }


def _close_engine() -> None:
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.close()
        finally:
            _ENGINE = None


def main() -> int:
    global _PROTOCOL_OUT
    # Keep stdout exclusively for the JSON-lines protocol. Coqui, torch and
    # transformers occasionally print to stdout; redirect ordinary output to
    # stderr so one noisy dependency cannot corrupt IPC framing.
    _PROTOCOL_OUT = sys.stdout
    sys.stdout = sys.stderr

    try:
        first = sys.stdin.readline()
        if not first:
            return 2
        message = json.loads(first)
        if message.get("type") != "init":
            raise RuntimeError("XTTS worker ilk mesaji init olmali.")
        _configure_engine(dict(message.get("config") or {}))
        assert _ENGINE is not None
        _emit(
            {
                "type": "ready",
                "pid": os.getpid(),
                "worker_logs": _drain_logs(),
                "runtime": _ENGINE.runtime_stats(),
                "effective_performance_mode": _ENGINE.effective_performance_mode,
            }
        )

        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                request = json.loads(raw)
                kind = request.get("type")
                if kind == "task":
                    _emit(_synthesize(dict(request.get("task") or {})))
                elif kind == "close":
                    _emit({"type": "closed", "pid": os.getpid()})
                    return 0
                elif kind == "ping":
                    _emit({"type": "pong", "pid": os.getpid()})
                else:
                    raise RuntimeError(f"Bilinmeyen XTTS worker mesaji: {kind!r}")
            except Exception as exc:
                _emit(
                    {
                        "type": "task_error",
                        "pid": os.getpid(),
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                        "worker_logs": _drain_logs(),
                    }
                )
        return 0
    except Exception as exc:
        _emit(
            {
                "type": "fatal",
                "pid": os.getpid(),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "worker_logs": _drain_logs(),
            }
        )
        return 3
    finally:
        _close_engine()


if __name__ == "__main__":
    raise SystemExit(main())
