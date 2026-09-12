import wave
from pathlib import Path
from zipfile import ZipFile

import pytest

from epub2m4b.core.models import AudioArtifact, PipelineOptions
from epub2m4b.core.pipeline import ConversionPipeline
from epub2m4b.tts.base import EngineInfo


def make_epub(path: Path) -> None:
    container = '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    opf = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Pipeline</dc:title><dc:creator>Tester</dc:creator></metadata>
    <manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/></manifest>
    <spine><itemref idref="c1"/></spine></package>'''
    chapter = "<html><body><h1>Bir</h1><p>Bu, pipeline testinde seslendirilecek yeterince uzun Türkçe bir paragraftır.</p></body></html>"
    with ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c1.xhtml", chapter)


class FakeEngine:
    info = EngineInfo(
        id="fake",
        name="Fake",
        description="test",
        license_name="test",
        license_url="https://example.invalid",
        commercial_use=False,
        recommended_max_chars=100,
        gpu_recommended=False,
    )

    def __init__(self):
        self.calls = 0
        self.texts = []

    def load(self):
        return None

    def reference_audio_required(self):
        return False

    def synthesize(self, text, output_path, reference_wav=None):
        self.calls += 1
        self.texts.append(text)
        rate = 8000
        frames = 800
        with wave.open(str(output_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"\x00\x00" * frames)
        return AudioArtifact(output_path, frames / rate, rate)

    def close(self):
        return None


def test_pipeline_success_cleans_workspace(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "book.m4b"
    make_epub(epub)
    engine = FakeEngine()

    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))

    def fake_assemble(**kwargs):
        kwargs["output_path"].write_bytes(b"m4b")

    monkeypatch.setattr("epub2m4b.core.pipeline.assemble_m4b", fake_assemble)
    pipeline = ConversionPipeline()
    result = pipeline.run(PipelineOptions(epub, output, "fake"))
    assert result == output
    assert output.read_bytes() == b"m4b"
    assert engine.calls >= 1
    runs = tmp_path / "cache" / "runs"
    assert not runs.exists() or not any(runs.iterdir())


def test_pipeline_failure_keeps_completed_cache(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "book.m4b"
    make_epub(epub)
    engine = FakeEngine()

    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mux fail")),
    )

    pipeline = ConversionPipeline()
    with pytest.raises(RuntimeError, match="mux fail"):
        pipeline.run(PipelineOptions(epub, output, "fake"))
    cached_wavs = list((tmp_path / "cache" / "runs").rglob("*.wav"))
    assert cached_wavs
    assert not list((tmp_path / "cache" / "runs").rglob("*.part.wav"))


def test_pipeline_only_synthesizes_selected_toc_chapters(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "selected.m4b"
    container = '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    opf = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Select</dc:title></metadata>
    <manifest>
      <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
      <item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
    </manifest>
    <spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'''
    c1 = "<html><body><h1>Bir</h1><p>Birinci bölüm kesinlikle seslendirilmemelidir ve yeterince uzundur.</p></body></html>"
    c2 = "<html><body><h1>İki</h1><p>İkinci bölüm seçildiği için seslendirilmelidir ve yeterince uzundur.</p></body></html>"
    with ZipFile(epub, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c1.xhtml", c1)
        zf.writestr("OEBPS/c2.xhtml", c2)

    engine = FakeEngine()
    assembled = {}
    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))

    def fake_assemble(**kwargs):
        assembled["timings"] = kwargs["timings"]
        kwargs["output_path"].write_bytes(b"m4b")

    monkeypatch.setattr("epub2m4b.core.pipeline.assemble_m4b", fake_assemble)
    pipeline = ConversionPipeline()
    pipeline.run(PipelineOptions(epub, output, "fake", selected_chapter_indices=(2,)))

    spoken = " ".join(engine.texts)
    assert "İkinci bölüm" in spoken
    assert "Birinci bölüm" not in spoken
    assert [timing.title for timing in assembled["timings"]] == ["İki"]


def test_pipeline_emits_performance_stats(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "stats.m4b"
    make_epub(epub)
    engine = FakeEngine()
    engine.runtime_stats = lambda: {"device": "cuda", "gpu_name": "Test GPU", "gpu_util_percent": 50}

    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )
    snapshots = []
    pipeline = ConversionPipeline(stats=snapshots.append)
    pipeline.run(PipelineOptions(epub, output, "fake"))

    assert snapshots
    last = snapshots[-1]
    assert last["gpu_name"] == "Test GPU"
    assert last["gpu_util_percent"] == 50
    assert last["realtime_factor"] > 0
    assert last["processed_chars"] == last["total_chars"]


def test_chunk_cache_key_ignores_worker_count():
    base = {"voice_mode": "builtin", "speaker": "A", "speed": 1.0, "performance_mode": "optimized"}
    one = ConversionPipeline._chunk_key("xtts", "metin", {**base, "worker_count": 1})
    two = ConversionPipeline._chunk_key("xtts", "metin", {**base, "worker_count": 2})
    assert one == two


def test_performance_tracker_hides_eta_during_warmup_and_emits_final_factor():
    from epub2m4b.core.pipeline import _PerformanceTracker

    tracker = _PerformanceTracker(total_chars=1000, run_started=0.0, workers=1)
    # Simulate five fast chunks; ETA should remain hidden until the warmup threshold.
    for index in range(5):
        tracker.record(
            chars=100,
            audio_seconds=10.0,
            cached=False,
            worker_wall_seconds=5.0,
            now=float(index + 1),
        )
    mid = tracker.snapshot(now=6.0)
    assert mid["eta_seconds"] is None
    assert mid["eta_warmup"] is True

    for index in range(5, 10):
        tracker.record(
            chars=100,
            audio_seconds=10.0,
            cached=False,
            worker_wall_seconds=5.0,
            now=float(index + 1),
        )
    final = tracker.snapshot(now=11.0)
    assert final["eta_seconds"] == 0.0
    assert final["realtime_factor"] > 0
    assert final["worker_realtime_factor"] == pytest.approx(2.0)


def test_pipeline_selects_two_worker_xtts_path(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "parallel.m4b"
    make_epub(epub)

    class FakeXTTS(FakeEngine):
        info = EngineInfo(
            id="xtts",
            name="Fake XTTS",
            description="test",
            license_name="test",
            license_url="https://example.invalid",
            commercial_use=False,
            recommended_max_chars=100,
            gpu_recommended=True,
        )

    engine = FakeXTTS()
    called = {"parallel": 0}
    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr("epub2m4b.core.pipeline.ConversionPipeline._resolve_device", lambda self, _device: "cuda")
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )

    def fake_parallel(self, *, jobs, tracker, workers, **_kwargs):
        called["parallel"] += 1
        assert workers == 2
        for job in jobs:
            rate = 8000
            frames = 800
            with wave.open(str(job.wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(b"\x00\x00" * frames)
            job.duration = frames / rate
            tracker.record(
                chars=len(job.text),
                audio_seconds=job.duration,
                cached=False,
                worker_wall_seconds=0.05,
            )
        return {"device": "cuda"}, 2

    monkeypatch.setattr(ConversionPipeline, "_run_parallel_xtts_jobs", fake_parallel)
    options = PipelineOptions(
        epub,
        output,
        "xtts",
        accept_model_license=True,
        engine_options={"worker_count": 2, "performance_mode": "optimized"},
    )
    ConversionPipeline().run(options)

    assert called["parallel"] == 1
    assert output.is_file()


def test_pipeline_selects_auto_xtts_path_with_worker_zero(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "auto.m4b"
    make_epub(epub)

    class FakeXTTS(FakeEngine):
        info = EngineInfo(
            id="xtts",
            name="Fake XTTS",
            description="test",
            license_name="test",
            license_url="https://example.invalid",
            commercial_use=False,
            recommended_max_chars=100,
            gpu_recommended=True,
        )

    engine = FakeXTTS()
    seen = {}
    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr("epub2m4b.core.pipeline.ConversionPipeline._resolve_device", lambda self, _device: "cuda")
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )

    def fake_parallel(self, *, jobs, tracker, workers, **_kwargs):
        seen["workers"] = workers
        for job in jobs:
            rate = 8000
            frames = 800
            with wave.open(str(job.wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(b"\x00\x00" * frames)
            job.duration = frames / rate
            tracker.record(chars=len(job.text), audio_seconds=job.duration, cached=False, worker_wall_seconds=0.05)
        return {"device": "cuda"}, 3

    monkeypatch.setattr(ConversionPipeline, "_run_parallel_xtts_jobs", fake_parallel)
    options = PipelineOptions(
        epub,
        output,
        "xtts",
        accept_model_license=True,
        engine_options={"worker_count": 0, "performance_mode": "optimized"},
    )
    ConversionPipeline().run(options)

    assert seen["workers"] == 0
    assert output.is_file()


def test_parallel_xtts_failure_falls_back_to_single_worker_and_reuses_completed_chunk(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "fallback.m4b"
    make_epub(epub)

    class FakeXTTS(FakeEngine):
        info = EngineInfo(
            id="xtts",
            name="Fake XTTS",
            description="test",
            license_name="test",
            license_url="https://example.invalid",
            commercial_use=False,
            recommended_max_chars=80,
            gpu_recommended=True,
        )

    engine = FakeXTTS()
    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr("epub2m4b.core.pipeline.ConversionPipeline._resolve_device", lambda self, _device: "cuda")
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )

    def flaky_parallel(self, *, jobs, tracker, **_kwargs):
        first = jobs[0]
        rate = 8000
        frames = 800
        with wave.open(str(first.wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"\x00\x00" * frames)
        first.duration = frames / rate
        tracker.record(chars=len(first.text), audio_seconds=first.duration, cached=False, worker_wall_seconds=0.05)
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(ConversionPipeline, "_run_parallel_xtts_jobs", flaky_parallel)
    options = PipelineOptions(
        epub,
        output,
        "xtts",
        accept_model_license=True,
        engine_options={"worker_count": 2, "performance_mode": "optimized"},
    )
    ConversionPipeline().run(options)

    assert output.is_file()
    # The already published first parallel chunk is converted to a cache hit,
    # so the single-worker fallback only synthesizes the remaining chunks.
    assert engine.calls >= 1


def test_pipeline_defensively_repairs_oversized_chunker_output(monkeypatch, tmp_path):
    epub = tmp_path / "book.epub"
    output = tmp_path / "repaired.m4b"
    make_epub(epub)
    engine = FakeEngine()

    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr("epub2m4b.core.pipeline.chunk_text", lambda _text, _limit: ["x" * 150])
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )

    ConversionPipeline().run(PipelineOptions(epub, output, "fake"))

    assert engine.texts
    assert all(len(text) <= FakeEngine.info.recommended_max_chars for text in engine.texts)
    assert "".join(engine.texts) == "x" * 150


def test_pipeline_defaults_to_toc_listed_chapters_when_navigation_exists(monkeypatch, tmp_path):
    epub = tmp_path / "toc-default.epub"
    output = tmp_path / "toc-default.m4b"
    container = '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
    <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    opf = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>TOC Default</dc:title></metadata>
    <manifest>
      <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
      <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
      <item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
    </manifest>
    <spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'''
    nav = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
    <nav epub:type="toc"><ol><li><a href="c1.xhtml">Ana</a></li></ol></nav></body></html>'''
    c1 = "<html><body><h1>Ana</h1><p>TOC içindeki bölüm varsayılan olarak seslendirilmelidir ve yeterince uzundur.</p></body></html>"
    c2 = "<html><body><h1>Ek</h1><p>TOC dışında kalan spine bölümü varsayılan olarak atlanmalıdır ve yeterince uzundur.</p></body></html>"
    with ZipFile(epub, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/c1.xhtml", c1)
        zf.writestr("OEBPS/c2.xhtml", c2)

    engine = FakeEngine()
    monkeypatch.setattr("epub2m4b.core.pipeline.create_engine", lambda *a, **k: engine)
    monkeypatch.setattr("epub2m4b.core.pipeline.user_cache_dir", lambda _name: str(tmp_path / "cache"))
    monkeypatch.setattr("epub2m4b.core.pipeline.require_ffmpeg", lambda: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(
        "epub2m4b.core.pipeline.assemble_m4b",
        lambda **kwargs: kwargs["output_path"].write_bytes(b"m4b"),
    )

    ConversionPipeline().run(PipelineOptions(epub, output, "fake"))
    spoken = " ".join(engine.texts)
    assert "TOC içindeki bölüm" in spoken
    assert "TOC dışında kalan" not in spoken
