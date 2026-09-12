import time

from epub2m4b.tts.xtts_subprocess_pool import WorkerReady, XTTSSubprocessPool


def test_subprocess_pool_runs_tasks_with_four_workers(monkeypatch):
    from epub2m4b.tts import xtts_subprocess_pool as module

    seen_workers = set()

    class FakeWorker:
        def __init__(self, index, config, log):
            self.index = index
            self.config = config
            self.log = log
            self.ready = None

        def start(self, timeout=600.0):
            self.ready = WorkerReady(
                pid=1000 + self.index,
                runtime={"vram_allocated_gb": 1.5},
                effective_performance_mode="optimized",
            )
            return self.ready

        def run_task(self, task, timeout=None):
            time.sleep(0.005)
            seen_workers.add(self.index)
            return {
                "type": "result",
                "task_id": task["task_id"],
                "duration_seconds": 1.0,
                "worker_pid": 1000 + self.index,
                "runtime": {"vram_allocated_gb": 1.5},
                "effective_performance_mode": "optimized",
            }

        def close(self, timeout=10.0):
            return None

        def terminate(self):
            return None

    monkeypatch.setattr(module, "_WorkerProcess", FakeWorker)
    pool = XTTSSubprocessPool({"device": "cuda"}, 4, log=lambda _message: None)
    ready = pool.start()
    assert len(ready) == 4
    assert pool.active_workers == 4

    results = []
    tasks = [{"task_id": str(index), "text": "x", "output_path": "x.wav"} for index in range(16)]
    pool.map_tasks(tasks, results.append)
    assert len(results) == 16
    assert len(seen_workers) == 4


def test_subprocess_pool_keeps_ready_workers_when_one_start_fails(monkeypatch):
    from epub2m4b.tts import xtts_subprocess_pool as module

    class FakeWorker:
        def __init__(self, index, config, log):
            self.index = index
            self.ready = None

        def start(self, timeout=600.0):
            if self.index == 1:
                raise RuntimeError("simulated startup failure")
            self.ready = WorkerReady(self.index + 10, {}, "optimized")
            return self.ready

        def close(self, timeout=10.0):
            return None

        def terminate(self):
            return None

    monkeypatch.setattr(module, "_WorkerProcess", FakeWorker)
    messages = []
    pool = XTTSSubprocessPool({"device": "cuda"}, 2, log=messages.append)
    pool.start()
    assert pool.active_workers == 1
    assert any("2 -> 1" in message for message in messages)
