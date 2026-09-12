from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


AUTO_WORKERS = 0
MAX_WORKERS = 4
AUTOTUNE_TARGET_REALTIME = 4.0
AUTOTUNE_VRAM_RESERVE_GB = 2.0
AUTOTUNE_ESTIMATED_WORKER_GB = 2.5


class XTTSWorkerError(RuntimeError):
    pass


@dataclass(slots=True)
class WorkerReady:
    pid: int
    runtime: dict[str, Any]
    effective_performance_mode: str


@dataclass(slots=True)
class AutoTuneResult:
    chosen_workers: int
    factors: dict[int, float]
    target_realtime: float
    target_reached: bool


def prioritize_tasks(tasks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schedule expensive chunks first while final audiobook order stays file-based.

    XTTS cost correlates reasonably with text length. Longest-processing-time-first
    reduces the tail where one worker is left with a long final chunk while the
    others are idle. Audio ordering is restored later by the pipeline, so dispatch
    order is free to optimize makespan.
    """

    return sorted(
        list(tasks),
        key=lambda task: (-len(str(task.get("text") or "")), str(task.get("task_id") or "")),
    )


def choose_best_worker_count(
    factors: dict[int, float],
    *,
    target_realtime: float = AUTOTUNE_TARGET_REALTIME,
    tie_ratio: float = 0.03,
) -> int:
    """Pick the smallest count that reaches target, otherwise the fastest count.

    If two configurations are within ``tie_ratio`` of the best result, the lower
    worker count wins to leave VRAM/headroom for Windows and avoid extra CUDA
    context switching for no meaningful throughput gain.
    """

    valid = {int(count): float(value) for count, value in factors.items() if int(count) > 0 and value > 0}
    if not valid:
        return 1
    for count in sorted(valid):
        if valid[count] >= target_realtime:
            return count
    best_factor = max(valid.values())
    threshold = best_factor * (1.0 - max(0.0, tie_ratio))
    return min(count for count, factor in valid.items() if factor >= threshold)


class _WorkerProcess:
    def __init__(self, index: int, config: dict[str, Any], log: Callable[[str], None]):
        self.index = index
        self.config = dict(config)
        self.log = log
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self.ready: WorkerReady | None = None
        self._closed = False

    def start(self, timeout: float = 600.0) -> WorkerReady:
        if self.process is not None:
            if self.ready is None:
                raise XTTSWorkerError("Worker sureci var ancak hazir degil.")
            return self.ready

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        # Multiple XTTS subprocesses must not each create a large CPU thread pool.
        # Limiting host-side math threads usually feeds the GPU more consistently
        # and prevents 3-4 worker mode from becoming CPU scheduler bound.
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        env.setdefault("NUMEXPR_NUM_THREADS", "1")
        env.setdefault("TOKENIZERS_PARALLELISM", "false")
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [sys.executable, "-u", "-m", "epub2m4b.tts.xtts_worker_process"]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self._stdout_thread = threading.Thread(target=self._read_stdout, name=f"xtts-ipc-{self.index}", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name=f"xtts-log-{self.index}", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._send({"type": "init", "config": self.config})

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.terminate()
                raise XTTSWorkerError(f"XTTS worker {self.index + 1} model yukleme zaman asimina ugradi.")
            message = self._wait_message(min(remaining, 1.0))
            if message is None:
                if self.process.poll() is not None:
                    raise XTTSWorkerError(
                        f"XTTS worker {self.index + 1} baslatilamadi; cikis kodu {self.process.returncode}."
                    )
                continue
            kind = message.get("type")
            if kind == "ready":
                for line in message.get("worker_logs") or []:
                    self.log(f"[XTTS worker {self.index + 1}] {line}")
                self.ready = WorkerReady(
                    pid=int(message.get("pid") or self.process.pid),
                    runtime=dict(message.get("runtime") or {}),
                    effective_performance_mode=str(message.get("effective_performance_mode") or ""),
                )
                return self.ready
            if kind in {"fatal", "task_error"}:
                for line in message.get("worker_logs") or []:
                    self.log(f"[XTTS worker {self.index + 1}] {line}")
                detail = str(message.get("error") or "bilinmeyen worker hatasi")
                tb = str(message.get("traceback") or "").strip()
                if tb:
                    self.log(f"[XTTS worker {self.index + 1} traceback]\n{tb}")
                self.terminate()
                raise XTTSWorkerError(f"XTTS worker {self.index + 1} baslatilamadi: {detail}")

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            for raw in self.process.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    self.log(f"[XTTS worker {self.index + 1} protokol-disi] {raw}")
                    continue
                self.messages.put(payload)
        finally:
            self.messages.put({"type": "eof", "returncode": self.process.poll()})

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        for raw in self.process.stderr:
            line = raw.rstrip()
            if line:
                self.log(f"[XTTS worker {self.index + 1}] {line}")

    def _send(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise XTTSWorkerError("XTTS worker sureci baslatilmadi.")
        if self.process.poll() is not None:
            raise XTTSWorkerError(
                f"XTTS worker {self.index + 1} beklenmedik bicimde sonlandi (kod {self.process.returncode})."
            )
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise XTTSWorkerError(f"XTTS worker {self.index + 1} IPC yazma hatasi: {exc}") from exc

    def _wait_message(self, timeout: float | None) -> dict[str, Any] | None:
        try:
            return self.messages.get(timeout=timeout)
        except queue.Empty:
            return None

    def run_task(self, task: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        if self.ready is None:
            raise XTTSWorkerError(f"XTTS worker {self.index + 1} hazir degil.")
        self._send({"type": "task", "task": task})
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait = 1.0
            if deadline is not None:
                wait = min(wait, max(0.0, deadline - time.monotonic()))
                if wait <= 0:
                    raise XTTSWorkerError(f"XTTS worker {self.index + 1} gorev zaman asimi.")
            message = self._wait_message(wait)
            if message is None:
                if self.process is not None and self.process.poll() is not None:
                    raise XTTSWorkerError(
                        f"XTTS worker {self.index + 1} gorev sirasinda sonlandi (kod {self.process.returncode})."
                    )
                continue
            kind = message.get("type")
            if kind == "result":
                return message
            if kind == "task_error":
                for line in message.get("worker_logs") or []:
                    self.log(f"[XTTS worker {self.index + 1}] {line}")
                tb = str(message.get("traceback") or "").strip()
                if tb:
                    self.log(f"[XTTS worker {self.index + 1} traceback]\n{tb}")
                raise XTTSWorkerError(
                    f"XTTS worker {self.index + 1} gorev hatasi: {message.get('error') or 'bilinmeyen hata'}"
                )
            if kind in {"fatal", "eof"}:
                raise XTTSWorkerError(
                    f"XTTS worker {self.index + 1} beklenmedik bicimde sonlandi: "
                    f"{message.get('error') or message.get('returncode') or 'EOF'}"
                )

    def close(self, timeout: float = 10.0) -> None:
        if self._closed:
            return
        self._closed = True
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                self._send({"type": "close"})
            except Exception:
                pass
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.terminate()
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

    def terminate(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


class XTTSSubprocessPool:
    """Persistent XTTS worker pool safe to launch from a Qt QThread.

    ``worker_count=0`` enables VRAM-aware auto mode. The pool loads up to four
    workers, benchmarks 1..N using the already-loaded models, and can then trim
    unused workers so the long book conversion runs with the fastest measured
    configuration rather than a guessed worker count.
    """

    def __init__(
        self,
        config: dict[str, Any],
        worker_count: int,
        log: Callable[[str], None] = print,
        startup_timeout: float = 600.0,
    ):
        self.config = dict(config)
        raw_count = int(worker_count)
        self.auto_mode = raw_count == AUTO_WORKERS
        self.requested_workers = AUTO_WORKERS if self.auto_mode else max(1, min(raw_count, MAX_WORKERS))
        self.max_workers = MAX_WORKERS if self.auto_mode else self.requested_workers
        self.log = log
        self.startup_timeout = startup_timeout
        self.workers: list[_WorkerProcess] = []

    def _auto_worker_cap(self) -> int:
        if not self.auto_mode:
            return self.max_workers
        try:
            from epub2m4b.core.gpu import nvidia_runtime_stats

            stats = nvidia_runtime_stats(str(self.config.get("device") or "cuda"), min_interval=0.0)
            total = float(stats.get("vram_device_total_gb") or stats.get("vram_total_gb") or 0.0)
            used = float(stats.get("vram_device_used_gb") or 0.0)
            if total > 0:
                free = max(0.0, total - used)
                by_memory = int(max(0.0, free - AUTOTUNE_VRAM_RESERVE_GB) // AUTOTUNE_ESTIMATED_WORKER_GB)
                cap = max(1, min(MAX_WORKERS, by_memory))
                self.log(
                    "XTTS AutoTune VRAM on-kontrolu: "
                    f"cihaz {used:.1f}/{total:.1f} GB, tahmini guvenli ust sinir={cap} worker."
                )
                return cap
        except Exception as exc:
            self.log(f"XTTS AutoTune VRAM on-kontrolu atlandi: {type(exc).__name__}: {exc}")
        return MAX_WORKERS

    def start(self) -> list[WorkerReady]:
        if self.workers:
            return [worker.ready for worker in self.workers if worker.ready is not None]

        start_count = self._auto_worker_cap()
        label = f"auto (en fazla {start_count})" if self.auto_mode else str(start_count)
        self.log(
            f"XTTS subprocess pool baslatiliyor: istenen worker={label}. "
            "Her worker ayri Python/CUDA surecidir."
        )
        candidates = [_WorkerProcess(i, self.config, self.log) for i in range(start_count)]
        failures: list[str] = []
        ready: list[tuple[_WorkerProcess, WorkerReady]] = []

        if self.auto_mode:
            # Auto mode starts workers one by one. This is slower than a burst
            # startup but lets us re-check device-wide free VRAM after every
            # model and stop before Windows/WDDM is pushed into an OOM spiral.
            for worker in candidates:
                try:
                    state = worker.start(self.startup_timeout)
                except BaseException as exc:  # noqa: BLE001
                    worker.terminate()
                    failures.append(str(exc))
                    break
                ready.append((worker, state))
                self.log(
                    f"XTTS worker {worker.index + 1} hazir: PID={state.pid}; "
                    f"mod={state.effective_performance_mode or '?'}"
                )
                if len(ready) >= start_count:
                    continue
                try:
                    from epub2m4b.core.gpu import nvidia_runtime_stats

                    stats = nvidia_runtime_stats(str(self.config.get("device") or "cuda"), min_interval=0.0)
                    total = float(stats.get("vram_device_total_gb") or stats.get("vram_total_gb") or 0.0)
                    used = float(stats.get("vram_device_used_gb") or 0.0)
                    if total > 0 and used > 0:
                        free = max(0.0, total - used)
                        required = AUTOTUNE_VRAM_RESERVE_GB + AUTOTUNE_ESTIMATED_WORKER_GB
                        if free < required:
                            self.log(
                                "XTTS AutoTune VRAM korumasi: "
                                f"kalan {free:.1f} GB < {required:.1f} GB; "
                                f"{len(ready)} worker ile sinirlandi."
                            )
                            break
                except Exception:
                    pass
        else:
            results: queue.Queue[tuple[_WorkerProcess, WorkerReady | None, BaseException | None]] = queue.Queue()

            def starter(worker: _WorkerProcess) -> None:
                try:
                    results.put((worker, worker.start(self.startup_timeout), None))
                except BaseException as exc:  # noqa: BLE001 - returned to parent thread
                    results.put((worker, None, exc))

            threads = [threading.Thread(target=starter, args=(worker,), daemon=True) for worker in candidates]
            for thread in threads:
                thread.start()

            for _ in candidates:
                worker, state, error = results.get()
                if error is not None or state is None:
                    worker.terminate()
                    failures.append(str(error or "bilinmeyen baslatma hatasi"))
                else:
                    ready.append((worker, state))
                    self.log(
                        f"XTTS worker {worker.index + 1} hazir: PID={state.pid}; "
                        f"mod={state.effective_performance_mode or '?'}"
                    )

        ready.sort(key=lambda item: item[0].index)
        self.workers = [item[0] for item in ready]
        if failures:
            self.log("XTTS worker baslatma uyarilari: " + " | ".join(failures))
        if not self.workers:
            raise XTTSWorkerError("Hicbir XTTS subprocess worker baslatilamadi. " + " | ".join(failures))
        if not self.auto_mode and len(self.workers) < self.requested_workers:
            self.log(
                f"XTTS worker sayisi dusuruldu: {self.requested_workers} -> {len(self.workers)}. "
                "Calisan worker'larla devam ediliyor."
            )
        return [worker.ready for worker in self.workers if worker.ready is not None]

    @property
    def active_workers(self) -> int:
        return len(self.workers)

    def map_tasks(
        self,
        tasks: Iterable[dict[str, Any]],
        on_result: Callable[[dict[str, Any]], None],
        cancel_check: Callable[[], None] | None = None,
        *,
        worker_limit: int | None = None,
        prioritize: bool = True,
    ) -> None:
        if not self.workers:
            self.start()
        limit = self.active_workers if worker_limit is None else max(1, min(int(worker_limit), self.active_workers))
        selected_workers = self.workers[:limit]
        items = prioritize_tasks(tasks) if prioritize else list(tasks)
        if not items:
            return
        task_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        for task in items:
            task_queue.put(task)
        results: queue.Queue[tuple[dict[str, Any] | None, BaseException | None]] = queue.Queue()
        stop = threading.Event()

        def runner(worker: _WorkerProcess) -> None:
            while not stop.is_set():
                try:
                    task = task_queue.get_nowait()
                except queue.Empty:
                    return
                try:
                    result = worker.run_task(task)
                    results.put((result, None))
                except BaseException as exc:  # noqa: BLE001
                    stop.set()
                    results.put((None, exc))
                    return

        threads = [threading.Thread(target=runner, args=(worker,), daemon=True) for worker in selected_workers]
        for thread in threads:
            thread.start()

        completed = 0
        try:
            while completed < len(items):
                if cancel_check is not None:
                    cancel_check()
                try:
                    result, error = results.get(timeout=0.2)
                except queue.Empty:
                    if stop.is_set():
                        raise XTTSWorkerError("XTTS worker havuzu durdu ancak hata mesaji alinamadi.")
                    continue
                if error is not None:
                    raise error
                assert result is not None
                on_result(result)
                completed += 1
        except BaseException:
            stop.set()
            for worker in selected_workers:
                worker.terminate()
            raise
        finally:
            for thread in threads:
                thread.join(timeout=0.5)

    def autotune_worker_count(
        self,
        *,
        output_dir: Path,
        texts: Sequence[str],
        cancel_check: Callable[[], None] | None = None,
        target_realtime: float = AUTOTUNE_TARGET_REALTIME,
    ) -> AutoTuneResult:
        if not self.workers:
            self.start()
        if not texts:
            raise ValueError("AutoTune icin en az bir test metni gerekli.")
        output_dir.mkdir(parents=True, exist_ok=True)
        active = self.active_workers
        if active <= 1:
            return AutoTuneResult(1, {1: 0.0}, target_realtime, False)

        # Warm every loaded model once before timing so first-token/model warmup
        # does not unfairly punish higher worker counts.
        warmups = [
            {
                "task_id": f"autotune-warmup-{index}",
                "text": texts[index % len(texts)],
                "output_path": str(output_dir / f"warmup_{index}.wav"),
            }
            for index in range(active)
        ]
        self.log(f"XTTS AutoTune: {active} worker isiniyor...")
        self.map_tasks(warmups, lambda _result: None, cancel_check, worker_limit=active)

        factors: dict[int, float] = {}
        for count in range(1, active + 1):
            if cancel_check is not None:
                cancel_check()
            # Use the same deterministic task ids/texts at every count so seeds
            # and generated durations stay comparable. More tasks than workers
            # make scheduler/context-switch effects visible.
            task_count = max(8, count * 4)
            tasks = [
                {
                    "task_id": f"autotune-bench-{index}",
                    "text": texts[index % len(texts)],
                    "output_path": str(output_dir / f"w{count}_{index}.wav"),
                }
                for index in range(task_count)
            ]
            audio_seconds = 0.0
            started = time.perf_counter()

            def collect(result: dict[str, Any]) -> None:
                nonlocal audio_seconds
                audio_seconds += float(result.get("duration_seconds") or 0.0)

            self.map_tasks(tasks, collect, cancel_check, worker_limit=count)
            wall = time.perf_counter() - started
            factor = audio_seconds / wall if wall > 0 else 0.0
            factors[count] = factor
            self.log(f"XTTS AutoTune: {count} worker = {factor:.2f}x realtime")
            if factor >= target_realtime:
                self.log(
                    f"XTTS AutoTune: {target_realtime:.2f}x hedefi {count} worker ile gecildi; "
                    "daha fazla CUDA context acilmiyor."
                )
                break

        chosen = choose_best_worker_count(factors, target_realtime=target_realtime)
        reached = factors.get(chosen, 0.0) >= target_realtime
        table = " | ".join(f"{count}w={factor:.2f}x" for count, factor in sorted(factors.items()))
        self.log(f"XTTS AutoTune sonucu: {table} -> secilen={chosen} worker")
        return AutoTuneResult(chosen, factors, target_realtime, reached)

    def trim_workers(self, count: int) -> None:
        keep = max(1, min(int(count), self.active_workers))
        extras = self.workers[keep:]
        if extras:
            self.log(f"XTTS AutoTune: kullanilmayan {len(extras)} worker kapatiliyor; aktif={keep}.")
        for worker in extras:
            worker.close()
        self.workers = self.workers[:keep]

    def close(self) -> None:
        for worker in self.workers:
            worker.close()
        self.workers.clear()

    def terminate(self) -> None:
        for worker in self.workers:
            worker.terminate()
        self.workers.clear()

    def __enter__(self) -> "XTTSSubprocessPool":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self.close()
        else:
            self.terminate()
