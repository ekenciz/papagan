from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from platformdirs import user_cache_dir

from epub2m4b.tts.registry import create_engine
from epub2m4b.tts.xtts_subprocess_pool import XTTSSubprocessPool

from .audio import assemble_m4b, audio_duration, require_ffmpeg
from .chunker import chunk_text
from .epub import parse_epub
from .gpu import nvidia_runtime_stats
from .models import ChapterTiming, PipelineOptions, QUALITY_PRESETS

ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]
StatsCallback = Callable[[dict[str, object]], None]


PERF_WARMUP_CHUNKS = 10


def _format_seconds(value: float) -> str:
    seconds = max(0, int(round(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} sa {minutes:02d} dk"
    if minutes:
        return f"{minutes} dk {seconds:02d} sn"
    return f"{seconds} sn"


class ConversionCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class _ChunkJob:
    sequence: int
    chapter_index: int
    chapter_title: str
    chunk_index: int
    chapter_chunk_count: int
    text: str
    wav_path: Path
    task_id: str
    duration: float | None = None
    cached: bool = False


class _PerformanceTracker:
    """Stable throughput/ETA accounting shared by sequential and parallel synthesis."""

    def __init__(self, total_chars: int, run_started: float, workers: int):
        self.total_chars = total_chars
        self.run_started = run_started
        self.workers = max(1, workers)
        self.processed_chars = 0
        self.completed_audio_seconds = 0.0
        self.synthesized_chars = 0
        self.synthesized_audio_seconds = 0.0
        self.worker_synthesis_seconds = 0.0
        self.cache_hits = 0
        self.uncached_chunks = 0
        self.first_uncached_completed_at: float | None = None
        self.first_uncached_audio_seconds = 0.0

    def record(
        self,
        *,
        chars: int,
        audio_seconds: float,
        cached: bool,
        worker_wall_seconds: float = 0.0,
        now: float | None = None,
    ) -> None:
        now = time.perf_counter() if now is None else now
        self.processed_chars += chars
        self.completed_audio_seconds += audio_seconds
        if cached:
            self.cache_hits += 1
            return
        self.uncached_chunks += 1
        self.synthesized_chars += chars
        self.synthesized_audio_seconds += audio_seconds
        self.worker_synthesis_seconds += max(0.0, worker_wall_seconds)
        if self.first_uncached_completed_at is None:
            self.first_uncached_completed_at = now
            self.first_uncached_audio_seconds = self.synthesized_audio_seconds

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        now = time.perf_counter() if now is None else now
        remaining_chars = max(self.total_chars - self.processed_chars, 0)

        realtime_factor = 0.0
        if (
            self.first_uncached_completed_at is not None
            and self.uncached_chunks >= PERF_WARMUP_CHUNKS
            and now > self.first_uncached_completed_at
        ):
            measured_audio = self.synthesized_audio_seconds - self.first_uncached_audio_seconds
            measured_wall = now - self.first_uncached_completed_at
            if measured_wall > 0:
                realtime_factor = measured_audio / measured_wall

        worker_realtime_factor = (
            self.synthesized_audio_seconds / self.worker_synthesis_seconds
            if self.worker_synthesis_seconds > 0
            else 0.0
        )
        end_to_end_factor = (
            self.synthesized_audio_seconds / (now - self.run_started)
            if self.synthesized_audio_seconds > 0 and now > self.run_started
            else 0.0
        )
        if remaining_chars == 0 and realtime_factor <= 0.0:
            # Short conversions can finish before the warmup threshold. Emit a
            # useful final number without re-introducing noisy early ETAs.
            realtime_factor = worker_realtime_factor if self.workers == 1 else end_to_end_factor

        eta_seconds: float | None = None
        if remaining_chars == 0:
            eta_seconds = 0.0
        elif (
            realtime_factor > 0
            and self.synthesized_chars > 0
            and self.uncached_chunks >= PERF_WARMUP_CHUNKS
        ):
            audio_per_char = self.synthesized_audio_seconds / self.synthesized_chars
            eta_seconds = remaining_chars * audio_per_char / realtime_factor

        return {
            "processed_chars": self.processed_chars,
            "total_chars": self.total_chars,
            "generated_audio_seconds": self.completed_audio_seconds,
            "synthesized_audio_seconds": self.synthesized_audio_seconds,
            "worker_synthesis_seconds": self.worker_synthesis_seconds,
            "realtime_factor": realtime_factor,
            "worker_realtime_factor": worker_realtime_factor,
            "end_to_end_realtime_factor": end_to_end_factor,
            "eta_seconds": eta_seconds,
            "eta_warmup": self.uncached_chunks < PERF_WARMUP_CHUNKS and remaining_chars > 0,
            "cache_hits": self.cache_hits,
            "uncached_chunks": self.uncached_chunks,
            "elapsed_wall_seconds": now - self.run_started,
            "workers": self.workers,
        }


class ConversionPipeline:
    def __init__(
        self,
        log: LogCallback | None = None,
        progress: ProgressCallback | None = None,
        stats: StatsCallback | None = None,
    ):
        self.log = log or (lambda _msg: None)
        self.progress = progress or (lambda _done, _total, _msg: None)
        self.stats = stats or (lambda _payload: None)
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise ConversionCancelled("Islem kullanici tarafindan iptal edildi.")

    @staticmethod
    def _book_fingerprint(path: Path, engine_id: str, reference_wav: Path | None) -> str:
        stat = path.stat()
        raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{engine_id}"
        if reference_wav and reference_wav.exists():
            rstat = reference_wav.stat()
            raw += f"|{reference_wav.resolve()}|{rstat.st_size}|{rstat.st_mtime_ns}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _chunk_key(engine_id: str, text: str, engine_options: dict) -> str:
        # Worker count is a scheduling choice and must not invalidate otherwise
        # identical audio cache entries. Performance mode can alter numerics, so
        # it intentionally remains in the cache key.
        cache_options = {k: v for k, v in engine_options.items() if k not in {"worker_count"}}
        payload = json.dumps(cache_options, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(f"{engine_id}\0{payload}\0{text}".encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _prepare_jobs(
        self,
        prepared: list[tuple[str, list[str]]],
        *,
        audio_dir: Path,
        engine_id: str,
        engine_options: dict,
    ) -> list[_ChunkJob]:
        jobs: list[_ChunkJob] = []
        sequence = 0
        for chapter_index, (chapter_title, chunks) in enumerate(prepared, start=1):
            for chunk_index, text in enumerate(chunks, start=1):
                sequence += 1
                key = self._chunk_key(engine_id, text, engine_options)
                wav_path = audio_dir / f"{chapter_index:04d}_{chunk_index:04d}_{key}.wav"
                duration: float | None = None
                cached = False
                if wav_path.exists() and wav_path.stat().st_size > 1024:
                    try:
                        cached_duration = audio_duration(wav_path)
                        if cached_duration > 0.05:
                            duration = cached_duration
                            cached = True
                    except Exception:
                        wav_path.unlink(missing_ok=True)
                jobs.append(
                    _ChunkJob(
                        sequence=sequence,
                        chapter_index=chapter_index,
                        chapter_title=chapter_title,
                        chunk_index=chunk_index,
                        chapter_chunk_count=len(chunks),
                        text=text,
                        wav_path=wav_path,
                        task_id=f"{chapter_index:04d}-{chunk_index:04d}-{key}",
                        duration=duration,
                        cached=cached,
                    )
                )
        return jobs

    def _emit_job_progress(
        self,
        tracker: _PerformanceTracker,
        *,
        job: _ChunkJob,
        completed_jobs: int,
        total_jobs: int,
        runtime: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "done": completed_jobs,
            "total": total_jobs,
            **tracker.snapshot(),
        }
        if runtime:
            payload.update(runtime)
        if extra:
            payload.update(extra)
        self.stats(payload)
        factor = float(payload.get("realtime_factor") or 0.0)
        uncached = int(payload.get("uncached_chunks") or 0)
        if not job.cached and (uncached == PERF_WARMUP_CHUNKS or (uncached > 0 and uncached % 25 == 0)):
            eta = payload.get("eta_seconds")
            eta_text = _format_seconds(float(eta)) if eta is not None else "isiniyor"
            if factor > 0:
                self.log(f"Performans: {factor:.2f}x realtime | tahmini kalan: {eta_text}")
            else:
                self.log(f"Performans: isinma {uncached}/{PERF_WARMUP_CHUNKS} parca")
        self.progress(
            completed_jobs,
            total_jobs,
            f"{job.chapter_title} - {job.chunk_index}/{job.chapter_chunk_count}",
        )

    def _run_sequential_jobs(
        self,
        *,
        engine,
        jobs: list[_ChunkJob],
        reference_wav: Path | None,
        tracker: _PerformanceTracker,
    ) -> dict[str, Any]:
        runtime_stats = getattr(engine, "runtime_stats", lambda: {})
        uncached = [job for job in jobs if not job.cached]
        if uncached:
            self.log("Model yukleniyor. Ilk calistirmada model dosyalari indirilebilir...")
            engine.load()
            initial_runtime = runtime_stats()
            if initial_runtime.get("gpu_name"):
                self.log(
                    "GPU: " + str(initial_runtime.get("gpu_name"))
                    + " | VRAM toplam: " + str(initial_runtime.get("vram_total_gb", "?")) + " GB"
                )
        completed = 0
        last_runtime: dict[str, Any] = runtime_stats() if uncached else {}
        current_chapter = None
        for job in jobs:
            self._check_cancel()
            if job.chapter_index != current_chapter:
                current_chapter = job.chapter_index
                self.log(f"Bolum {job.chapter_index}/{max(j.chapter_index for j in jobs)}: {job.chapter_title}")
            if job.cached:
                assert job.duration is not None
                self.log(f"Onbellekten kullanildi: {job.wav_path.name}")
                tracker.record(chars=len(job.text), audio_seconds=job.duration, cached=True)
            else:
                part_path = job.wav_path.with_name(job.wav_path.stem + ".part.wav")
                part_path.unlink(missing_ok=True)
                started = time.perf_counter()
                try:
                    artifact = engine.synthesize(job.text, part_path, reference_wav)
                    job.duration = artifact.duration_seconds
                    part_path.replace(job.wav_path)
                finally:
                    part_path.unlink(missing_ok=True)
                wall = time.perf_counter() - started
                tracker.record(
                    chars=len(job.text),
                    audio_seconds=float(job.duration),
                    cached=False,
                    worker_wall_seconds=wall,
                )
                last_runtime = runtime_stats()
            completed += 1
            self._emit_job_progress(
                tracker,
                job=job,
                completed_jobs=completed,
                total_jobs=len(jobs),
                runtime=last_runtime,
                extra={"effective_workers": 1},
            )
        return last_runtime

    def _run_parallel_xtts_jobs(
        self,
        *,
        options: PipelineOptions,
        jobs: list[_ChunkJob],
        tracker: _PerformanceTracker,
        workers: int,
        resolved_device: str,
    ) -> tuple[dict[str, Any], int]:
        from epub2m4b.tts.xtts import (
            DEFAULT_SPEAKER,
            PERFORMANCE_MODE_OPTIMIZED,
            VOICE_MODE_BUILTIN,
        )

        config = {
            "device": resolved_device,
            "accept_model_license": options.accept_model_license,
            "voice_mode": str(options.engine_options.get("voice_mode", VOICE_MODE_BUILTIN)),
            "speaker": str(options.engine_options.get("speaker", DEFAULT_SPEAKER)),
            "speed": float(options.engine_options.get("speed", 1.0)),
            "performance_mode": str(options.engine_options.get("performance_mode", PERFORMANCE_MODE_OPTIMIZED)),
            "reference_wav": str(options.reference_wav) if options.reference_wav else None,
        }
        self.log(
            f"XTTS paralel mod: {workers} bagimsiz subprocess worker; aygit={resolved_device}; "
            f"mod={config['performance_mode']}."
        )
        self.log(
            "Windows/Qt icin ProcessPool yerine kalici python -m worker surecleri kullaniliyor; "
            "bu yol spawn/QThread fallback sorununu onler."
        )

        completed = 0
        worker_allocated: dict[int, float] = {}
        effective_modes: dict[int, str] = {}
        last_runtime = nvidia_runtime_stats(resolved_device, min_interval=0.0)

        for job in jobs:
            if not job.cached:
                continue
            assert job.duration is not None
            self.log(f"Onbellekten kullanildi: {job.wav_path.name}")
            tracker.record(chars=len(job.text), audio_seconds=job.duration, cached=True)
            completed += 1
            self._emit_job_progress(
                tracker,
                job=job,
                completed_jobs=completed,
                total_jobs=len(jobs),
                runtime=last_runtime,
                extra={"effective_workers": workers},
            )

        pending_jobs = [job for job in jobs if not job.cached]
        if not pending_jobs:
            return last_runtime, workers

        pool = XTTSSubprocessPool(config, workers, log=self.log)
        try:
            ready = pool.start()
            active_workers = pool.active_workers
            tracker.workers = active_workers
            self.log(f"XTTS paralel havuz hazir: {active_workers}/{workers} worker aktif.")
            for state in ready:
                allocated = state.runtime.get("vram_allocated_gb")
                if allocated is not None:
                    worker_allocated[state.pid] = float(allocated)
                if state.effective_performance_mode:
                    effective_modes[state.pid] = state.effective_performance_mode

            jobs_by_id = {job.task_id: job for job in pending_jobs}

            def on_result(result: dict[str, Any]) -> None:
                nonlocal completed, last_runtime
                task_id = str(result.get("task_id") or "")
                job = jobs_by_id.get(task_id)
                if job is None:
                    raise RuntimeError(f"XTTS worker bilinmeyen task_id dondurdu: {task_id}")
                for message in result.get("worker_logs", []):
                    self.log(f"[XTTS worker {result.get('worker_pid', '?')}] {message}")
                job.duration = float(result["duration_seconds"])
                worker_wall = float(result.get("synth_wall_seconds") or 0.0)
                tracker.record(
                    chars=len(job.text),
                    audio_seconds=job.duration,
                    cached=False,
                    worker_wall_seconds=worker_wall,
                )
                pid = int(result.get("worker_pid") or 0)
                worker_runtime = dict(result.get("runtime") or {})
                allocated = worker_runtime.get("vram_allocated_gb")
                if pid and allocated is not None:
                    worker_allocated[pid] = float(allocated)
                mode = str(result.get("effective_performance_mode") or "")
                if pid and mode:
                    effective_modes[pid] = mode

                completed += 1
                last_runtime = nvidia_runtime_stats(resolved_device, min_interval=0.25)
                extra: dict[str, Any] = {
                    "effective_workers": active_workers,
                    "requested_workers": workers,
                    "vram_workers_allocated_gb": round(sum(worker_allocated.values()), 2),
                }
                if effective_modes:
                    extra["effective_performance_mode"] = "+".join(sorted(set(effective_modes.values())))
                self._emit_job_progress(
                    tracker,
                    job=job,
                    completed_jobs=completed,
                    total_jobs=len(jobs),
                    runtime=last_runtime,
                    extra=extra,
                )

            tasks = [
                {"task_id": job.task_id, "text": job.text, "output_path": str(job.wav_path)}
                for job in pending_jobs
            ]
            pool.map_tasks(tasks, on_result, cancel_check=self._check_cancel)
            return last_runtime, active_workers
        finally:
            pool.close()

    @staticmethod
    def _finalize_order(jobs: list[_ChunkJob]) -> tuple[list[Path], list[ChapterTiming], float]:
        ordered = sorted(jobs, key=lambda job: job.sequence)
        chunk_paths: list[Path] = []
        timings: list[ChapterTiming] = []
        elapsed = 0.0
        current_chapter: int | None = None
        chapter_title = ""
        chapter_start = 0.0
        for job in ordered:
            if job.duration is None:
                raise RuntimeError(f"TTS parcasi tamamlanmadi: {job.task_id}")
            if current_chapter is None:
                current_chapter = job.chapter_index
                chapter_title = job.chapter_title
                chapter_start = elapsed
            elif job.chapter_index != current_chapter:
                timings.append(
                    ChapterTiming(
                        title=chapter_title,
                        start_ms=round(chapter_start * 1000),
                        end_ms=max(round(elapsed * 1000), round(chapter_start * 1000) + 1),
                    )
                )
                current_chapter = job.chapter_index
                chapter_title = job.chapter_title
                chapter_start = elapsed
            chunk_paths.append(job.wav_path)
            elapsed += job.duration
        if current_chapter is not None:
            timings.append(
                ChapterTiming(
                    title=chapter_title,
                    start_ms=round(chapter_start * 1000),
                    end_ms=max(round(elapsed * 1000), round(chapter_start * 1000) + 1),
                )
            )
        return chunk_paths, timings, elapsed

    def run(self, options: PipelineOptions) -> Path:
        require_ffmpeg()
        if options.output_path.suffix.lower() != ".m4b":
            raise RuntimeError("Cikti dosyasi .m4b uzantili olmalidir.")
        self._check_cancel()
        self.log(f"EPUB okunuyor: {options.epub_path}")
        book = parse_epub(options.epub_path)
        self.log(f"Kitap: {book.metadata.title} - {book.metadata.author} ({len(book.chapters)} bolum)")

        chapters = book.chapters
        if options.selected_chapter_indices is not None:
            selected = set(options.selected_chapter_indices)
            chapters = [chapter for chapter in book.chapters if chapter.index in selected]
            self.log(f"TOC secimi: {len(chapters)}/{len(book.chapters)} bolum seslendirilecek.")
        if not chapters:
            raise RuntimeError("Seslendirilecek bolum secilmedi.")

        engine = create_engine(
            options.engine_id,
            device=options.device,
            accept_model_license=options.accept_model_license,
            log=self.log,
            **options.engine_options,
        )
        info = engine.info
        reference_required = engine.reference_audio_required()
        if reference_required:
            if not options.reference_wav or not options.reference_wav.is_file():
                raise RuntimeError(f"{info.name} icin referans WAV zorunludur.")
            if not options.voice_consent:
                raise RuntimeError("Referans ses icin kullanim izni/onayi verilmelidir.")
        if info.requires_license_ack and not options.accept_model_license:
            raise RuntimeError(f"{info.name} model lisansi kabul edilmelidir.")

        self.log(f"TTS motoru: {info.name}")
        prepared: list[tuple[str, list[str]]] = []
        total_chunks = 0
        total_chars = 0
        for chapter in chapters:
            chunks = chunk_text(chapter.text, info.recommended_max_chars)
            if chunks:
                prepared.append((chapter.title, chunks))
                total_chunks += len(chunks)
                total_chars += sum(len(chunk) for chunk in chunks)
        if total_chunks == 0:
            raise RuntimeError("Seslendirilecek metin parcasi olusturulamadi.")
        self.log(f"{total_chunks} TTS parcasi hazirlandi (hedef: <= {info.recommended_max_chars} karakter).")

        fingerprint = self._book_fingerprint(
            options.epub_path,
            options.engine_id,
            options.reference_wav if reference_required else None,
        )
        workspace = Path(user_cache_dir("epub-to-m4b")) / "runs" / fingerprint
        audio_dir = workspace / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        cover_path: Path | None = None
        if book.metadata.cover_bytes:
            cover_path = workspace / f"cover{book.metadata.cover_suffix}"
            cover_path.write_bytes(book.metadata.cover_bytes)

        jobs = self._prepare_jobs(
            prepared,
            audio_dir=audio_dir,
            engine_id=options.engine_id,
            engine_options=options.engine_options,
        )
        run_started = time.perf_counter()
        requested_workers = int(options.engine_options.get("worker_count", 1) or 1)
        requested_workers = max(1, min(requested_workers, 4))
        resolved_device = self._resolve_device(options.device)
        parallel_xtts = options.engine_id == "xtts" and requested_workers > 1 and resolved_device.startswith("cuda")
        if options.engine_id == "xtts" and requested_workers > 1 and not parallel_xtts:
            self.log("XTTS coklu-worker yalniz CUDA'da etkin; tek worker kullanilacak.")
        effective_workers = requested_workers if parallel_xtts else 1
        tracker = _PerformanceTracker(total_chars, run_started, effective_workers)

        succeeded = False
        try:
            if parallel_xtts:
                try:
                    _runtime, effective_workers = self._run_parallel_xtts_jobs(
                        options=options,
                        jobs=jobs,
                        tracker=tracker,
                        workers=effective_workers,
                        resolved_device=resolved_device,
                    )
                except ConversionCancelled:
                    raise
                except Exception as exc:
                    self.log(
                        "XTTS coklu-worker modu basarisiz oldu; tek-worker optimize fallback deneniyor: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    # Reuse any chunks that independent workers managed to publish
                    # before failing. The parent process has not loaded XTTS yet,
                    # so a clean single-worker fallback remains possible.
                    for job in jobs:
                        if job.duration is not None and job.wav_path.exists():
                            job.cached = True
                            continue
                        if job.wav_path.exists() and job.wav_path.stat().st_size > 1024:
                            try:
                                duration = audio_duration(job.wav_path)
                                if duration > 0.05:
                                    job.duration = duration
                                    job.cached = True
                            except Exception:
                                job.wav_path.unlink(missing_ok=True)
                    effective_workers = 1
                    tracker = _PerformanceTracker(total_chars, time.perf_counter(), 1)
                    self._run_sequential_jobs(
                        engine=engine,
                        jobs=jobs,
                        reference_wav=options.reference_wav,
                        tracker=tracker,
                    )
            else:
                self._run_sequential_jobs(
                    engine=engine,
                    jobs=jobs,
                    reference_wav=options.reference_wav,
                    tracker=tracker,
                )

            self._check_cancel()
            chunk_paths, timings, _elapsed = self._finalize_order(jobs)
            final = tracker.snapshot()
            factor = float(final.get("realtime_factor") or 0.0)
            e2e = float(final.get("end_to_end_realtime_factor") or 0.0)
            worker_factor = float(final.get("worker_realtime_factor") or 0.0)
            self.log(
                "Uretim ozeti: "
                f"worker={effective_workers} | aggregate={factor:.2f}x | "
                f"worker-ortalama={worker_factor:.2f}x | model-yukleme-dahil={e2e:.2f}x | "
                f"cache={int(final.get('cache_hits') or 0)}"
            )

            quality = QUALITY_PRESETS[options.quality_key]
            self.log(f"M4B kodlaniyor: {quality.label}")
            assemble_m4b(
                chunk_paths=chunk_paths,
                timings=timings,
                metadata=book.metadata,
                output_path=options.output_path,
                quality=quality,
                workspace=workspace,
                cover_path=cover_path,
                log=self.log,
            )
            self.log(f"Tamamlandi: {options.output_path}")
            succeeded = True
            return options.output_path
        finally:
            engine.close()
            if succeeded and not options.keep_work_files:
                shutil.rmtree(workspace, ignore_errors=True)
