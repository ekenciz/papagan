from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable


class XTTSWorkerError(RuntimeError):
    pass


@dataclass(slots=True)
class WorkerReady:
    pid: int
    runtime: dict[str, Any]
    effective_performance_mode: str


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
    """Persistent XTTS worker pool that is safe to launch from a Qt QThread.

    Windows ``multiprocessing``/``ProcessPoolExecutor`` uses ``spawn`` and may
    re-import the Qt entry point.  Starting explicit ``python -m`` worker
    subprocesses avoids that fragile bootstrap path and gives us a clean JSON
    protocol plus per-worker startup errors.
    """

    def __init__(
        self,
        config: dict[str, Any],
        worker_count: int,
        log: Callable[[str], None] = print,
        startup_timeout: float = 600.0,
    ):
        self.config = dict(config)
        self.requested_workers = max(1, min(int(worker_count), 4))
        self.log = log
        self.startup_timeout = startup_timeout
        self.workers: list[_WorkerProcess] = []

    def start(self) -> list[WorkerReady]:
        if self.workers:
            return [worker.ready for worker in self.workers if worker.ready is not None]

        self.log(
            f"XTTS subprocess pool baslatiliyor: istenen worker={self.requested_workers}. "
            "Her worker ayri Python/CUDA surecidir."
        )
        # Start concurrently: model files are already cached and RTX-class cards
        # can upload multiple model instances without serialising several minutes
        # of startup time. Failures are collected with their exact worker output.
        candidates = [_WorkerProcess(i, self.config, self.log) for i in range(self.requested_workers)]
        results: queue.Queue[tuple[_WorkerProcess, WorkerReady | None, BaseException | None]] = queue.Queue()

        def starter(worker: _WorkerProcess) -> None:
            try:
                results.put((worker, worker.start(self.startup_timeout), None))
            except BaseException as exc:  # noqa: BLE001 - returned to parent thread
                results.put((worker, None, exc))

        threads = [threading.Thread(target=starter, args=(worker,), daemon=True) for worker in candidates]
        for thread in threads:
            thread.start()

        failures: list[str] = []
        ready: list[tuple[_WorkerProcess, WorkerReady]] = []
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
        if len(self.workers) < self.requested_workers:
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
    ) -> None:
        if not self.workers:
            self.start()
        task_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        items = list(tasks)
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

        threads = [threading.Thread(target=runner, args=(worker,), daemon=True) for worker in self.workers]
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
            for worker in self.workers:
                worker.terminate()
            raise
        finally:
            for thread in threads:
                thread.join(timeout=0.5)

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
