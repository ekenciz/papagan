from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from platformdirs import user_cache_dir
from PySide6.QtCore import QThread, Signal

from epub2m4b.core.dependencies import install_engine_dependencies, install_xtts_deepspeed
from epub2m4b.core.models import PipelineOptions
from epub2m4b.core.pipeline import ConversionCancelled, ConversionPipeline
from epub2m4b.tts.xtts import XTTSEngine
from epub2m4b.tts.xtts_subprocess_pool import XTTSSubprocessPool


class ConversionWorker(QThread):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    stats_changed = Signal(dict)
    succeeded = Signal(str)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, options: PipelineOptions, parent=None):
        super().__init__(parent)
        self.options = options
        self.pipeline = ConversionPipeline(
            log=self.log_message.emit,
            progress=self.progress_changed.emit,
            stats=self.stats_changed.emit,
        )

    def run(self) -> None:
        try:
            output = self.pipeline.run(self.options)
            self.succeeded.emit(str(output))
        except ConversionCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:  # GUI sinirinda hata metne donusturulur.
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def cancel(self) -> None:
        self.pipeline.cancel()


class DependencyWorker(QThread):
    log_message = Signal(str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, engine_id: str, parent=None):
        super().__init__(parent)
        self.engine_id = engine_id

    def run(self) -> None:
        try:
            install_engine_dependencies(self.engine_id, self.log_message.emit)
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class DeepSpeedDependencyWorker(QThread):
    log_message = Signal(str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, *, install_build_tools: bool = False, parent=None):
        super().__init__(parent)
        self.install_build_tools = install_build_tools

    def run(self) -> None:
        try:
            install_xtts_deepspeed(
                self.log_message.emit,
                install_build_tools=self.install_build_tools,
            )
            self.succeeded.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class XTTSSpeakerWorker(QThread):
    log_message = Signal(str)
    speakers_ready = Signal(list)
    failed = Signal(str)

    def __init__(self, device: str, accept_model_license: bool, parent=None):
        super().__init__(parent)
        self.device = device
        self.accept_model_license = accept_model_license

    def run(self) -> None:
        engine = XTTSEngine(
            device=self.device,
            accept_model_license=self.accept_model_license,
            voice_mode="builtin",
            log=self.log_message.emit,
        )
        try:
            speakers = engine.list_speakers()
            self.speakers_ready.emit(speakers)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            engine.close()


class XTTSPreviewWorker(QThread):
    log_message = Signal(str)
    preview_ready = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        device: str,
        accept_model_license: bool,
        voice_mode: str,
        speaker: str,
        speed: float,
        performance_mode: str,
        reference_wav: Path | None,
        preview_text: str,
        parent=None,
    ):
        super().__init__(parent)
        self.device = device
        self.accept_model_license = accept_model_license
        self.voice_mode = voice_mode
        self.speaker = speaker
        self.speed = speed
        self.performance_mode = performance_mode
        self.reference_wav = reference_wav
        self.preview_text = preview_text

    def run(self) -> None:
        engine = XTTSEngine(
            device=self.device,
            accept_model_license=self.accept_model_license,
            voice_mode=self.voice_mode,
            speaker=self.speaker,
            speed=self.speed,
            performance_mode=self.performance_mode,
            log=self.log_message.emit,
        )
        try:
            preview_dir = Path(user_cache_dir("epub-to-m4b")) / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            output = preview_dir / f"xtts_{uuid4().hex[:12]}.wav"
            engine.synthesize(self.preview_text, output, self.reference_wav)
            self.preview_ready.emit(str(output))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            engine.close()


class XTTSBenchmarkWorker(QThread):
    log_message = Signal(str)
    benchmark_ready = Signal(dict)
    failed = Signal(str)

    _TEXTS = [
        "Bu kısa deneme, Türkçe sesli kitap üretim hızını ölçmek için hazırlanmıştır.",
        "Amaç, ekran kartının gerçek ses üretim performansını kararlı biçimde karşılaştırmaktır.",
        "Birden fazla XTTS worker kullanıldığında parçalar bağımsız süreçlerde eş zamanlı üretilir.",
        "DeepSpeed seçeneği destekleniyorsa GPT çıkarım katmanında ek hızlandırma denenir.",
        "Bu ölçüm model yükleme süresini değil, ısınma sonrasındaki üretim hızını temel alır.",
        "Sonuç dört kat gerçek zaman hedefinin ne kadarına ulaşıldığını doğrudan gösterecektir.",
        "Ses kalitesi korunurken toplam kitap süresini azaltmak için güvenli ayarlar tercih edilir.",
        "Aynı test metinleri kullanıldığı için farklı modlar arasında daha anlamlı karşılaştırma yapılabilir.",
    ]

    def __init__(
        self,
        *,
        device: str,
        accept_model_license: bool,
        voice_mode: str,
        speaker: str,
        speed: float,
        performance_mode: str,
        worker_count: int,
        reference_wav: Path | None,
        parent=None,
    ):
        super().__init__(parent)
        self.device = device
        self.accept_model_license = accept_model_license
        self.voice_mode = voice_mode
        self.speaker = speaker
        self.speed = speed
        self.performance_mode = performance_mode
        self.worker_count = max(1, min(int(worker_count), 4))
        self.reference_wav = reference_wav

    def _benchmark_single(self, root: Path) -> dict:
        engine = XTTSEngine(
            device=self.device,
            accept_model_license=self.accept_model_license,
            voice_mode=self.voice_mode,
            speaker=self.speaker,
            speed=self.speed,
            performance_mode=self.performance_mode,
            log=self.log_message.emit,
        )
        try:
            self.log_message.emit("Benchmark: XTTS modeli yukleniyor...")
            engine.load()
            # Two warmup chunks are intentionally excluded from timing.
            for index, text in enumerate(self._TEXTS[:2]):
                engine.synthesize(text, root / f"warmup_{index}.wav", self.reference_wav)
            audio_seconds = 0.0
            started = time.perf_counter()
            for index, text in enumerate(self._TEXTS[2:]):
                artifact = engine.synthesize(text, root / f"bench_{index}.wav", self.reference_wav)
                audio_seconds += artifact.duration_seconds
            wall = time.perf_counter() - started
            factor = audio_seconds / wall if wall > 0 else 0.0
            runtime = engine.runtime_stats()
            return {
                "realtime_factor": factor,
                "audio_seconds": audio_seconds,
                "wall_seconds": wall,
                "workers": 1,
                "effective_performance_mode": engine.effective_performance_mode,
                **runtime,
            }
        finally:
            engine.close()

    def _benchmark_parallel(self, root: Path) -> dict:
        config = {
            "device": self.device,
            "accept_model_license": self.accept_model_license,
            "voice_mode": self.voice_mode,
            "speaker": self.speaker,
            "speed": self.speed,
            "performance_mode": self.performance_mode,
            "reference_wav": str(self.reference_wav) if self.reference_wav else None,
        }
        self.log_message.emit(f"Benchmark: {self.worker_count} kalici XTTS subprocess worker yukleniyor...")
        pool = XTTSSubprocessPool(config, self.worker_count, log=self.log_message.emit)
        try:
            ready = pool.start()
            active_workers = pool.active_workers
            self.log_message.emit(f"Benchmark worker havuzu: {active_workers}/{self.worker_count} aktif.")

            warmup_tasks = []
            for index in range(max(active_workers * 2, 2)):
                warmup_tasks.append(
                    {
                        "task_id": f"warmup-{index}",
                        "text": self._TEXTS[index % 2],
                        "output_path": str(root / f"warmup_{index}.wav"),
                    }
                )
            pool.map_tasks(warmup_tasks, lambda _result: None)

            tasks = []
            # Enough tasks to keep 4 workers busy and amortize scheduler jitter.
            repeats = max(2, active_workers)
            for index, text in enumerate(self._TEXTS[2:] * repeats):
                tasks.append(
                    {
                        "task_id": f"bench-{index}",
                        "text": text,
                        "output_path": str(root / f"bench_{index}.wav"),
                    }
                )

            audio_seconds = 0.0
            modes: set[str] = set()
            worker_allocated: dict[int, float] = {}
            started = time.perf_counter()

            def collect(result: dict) -> None:
                nonlocal audio_seconds
                audio_seconds += float(result["duration_seconds"])
                mode = str(result.get("effective_performance_mode") or "")
                if mode:
                    modes.add(mode)
                pid = int(result.get("worker_pid") or 0)
                runtime = dict(result.get("runtime") or {})
                allocated = runtime.get("vram_allocated_gb")
                if pid and allocated is not None:
                    worker_allocated[pid] = float(allocated)

            pool.map_tasks(tasks, collect)
            wall = time.perf_counter() - started
            factor = audio_seconds / wall if wall > 0 else 0.0

            from epub2m4b.core.gpu import nvidia_runtime_stats

            runtime = nvidia_runtime_stats(self.device, min_interval=0.0)
            return {
                "realtime_factor": factor,
                "audio_seconds": audio_seconds,
                "wall_seconds": wall,
                "workers": active_workers,
                "requested_workers": self.worker_count,
                "effective_performance_mode": "+".join(sorted(modes)) if modes else self.performance_mode,
                "vram_workers_allocated_gb": round(sum(worker_allocated.values()), 2),
                **runtime,
            }
        finally:
            pool.close()

    def run(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="epub2m4b_xtts_bench_"))
        try:
            device = self.device
            if device == "auto":
                try:
                    import torch

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:
                    device = "cpu"
            self.device = device
            if self.worker_count > 1 and str(device).startswith("cuda"):
                result = self._benchmark_parallel(root)
            else:
                result = self._benchmark_single(root)
            self.benchmark_ready.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
