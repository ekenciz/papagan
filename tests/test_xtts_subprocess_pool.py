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


def test_prioritize_tasks_dispatches_longest_first():
    from epub2m4b.tts.xtts_subprocess_pool import prioritize_tasks

    tasks = [
        {"task_id": "short", "text": "abc"},
        {"task_id": "long", "text": "abcdefghij"},
        {"task_id": "mid", "text": "abcdef"},
    ]
    assert [task["task_id"] for task in prioritize_tasks(tasks)] == ["long", "mid", "short"]


def test_choose_best_worker_count_prefers_smallest_target_then_near_tie():
    from epub2m4b.tts.xtts_subprocess_pool import choose_best_worker_count

    assert choose_best_worker_count({1: 0.9, 2: 2.1, 3: 4.05, 4: 4.8}) == 3
    assert choose_best_worker_count({1: 0.9, 2: 2.0, 3: 3.02, 4: 3.10}) == 3


def test_subprocess_pool_worker_limit_uses_subset(monkeypatch):
    from epub2m4b.tts import xtts_subprocess_pool as module

    seen_workers = set()

    class FakeWorker:
        def __init__(self, index, config, log):
            self.index = index
            self.ready = None

        def start(self, timeout=600.0):
            self.ready = WorkerReady(self.index + 100, {}, "optimized")
            return self.ready

        def run_task(self, task, timeout=None):
            time.sleep(0.002)
            seen_workers.add(self.index)
            return {"type": "result", "task_id": task["task_id"], "duration_seconds": 0.01}

        def close(self, timeout=10.0):
            return None

        def terminate(self):
            return None

    monkeypatch.setattr(module, "_WorkerProcess", FakeWorker)
    pool = XTTSSubprocessPool({"device": "cuda"}, 4, log=lambda _message: None)
    pool.start()
    results = []
    tasks = [{"task_id": str(index), "text": "x" * (index + 1), "output_path": "x.wav"} for index in range(20)]
    pool.map_tasks(tasks, results.append, worker_limit=2)
    assert len(results) == 20
    assert seen_workers <= {0, 1}
    assert seen_workers == {0, 1}


def test_autotune_selects_fastest_available_count(monkeypatch, tmp_path):
    from epub2m4b.tts import xtts_subprocess_pool as module

    class FakeWorker:
        def __init__(self, index, config, log):
            self.index = index
            self.ready = None

        def start(self, timeout=600.0):
            self.ready = WorkerReady(self.index + 200, {"vram_allocated_gb": 0.1}, "optimized")
            return self.ready

        def run_task(self, task, timeout=None):
            time.sleep(0.02)
            return {
                "type": "result",
                "task_id": task["task_id"],
                "duration_seconds": 0.01,
                "worker_pid": self.index + 200,
            }

        def close(self, timeout=10.0):
            return None

        def terminate(self):
            return None

    monkeypatch.setattr(module, "_WorkerProcess", FakeWorker)
    monkeypatch.setattr(module.XTTSSubprocessPool, "_auto_worker_cap", lambda self: 4)
    pool = XTTSSubprocessPool({"device": "cuda"}, 0, log=lambda _message: None)
    pool.start()
    result = pool.autotune_worker_count(output_dir=tmp_path, texts=["a" * 20, "b" * 30], target_realtime=4.0)
    # Thread scheduling jitter can make 3 or 4 fake workers win on a busy CI host.
    # The invariant under test is that AutoTune chooses the fastest measured count,
    # not that a wall-clock sleep microbenchmark scales perfectly linearly.
    fastest = max(result.factors, key=result.factors.get)
    assert result.chosen_workers == fastest
    assert set(result.factors) == {1, 2, 3, 4}
