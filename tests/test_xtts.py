from types import SimpleNamespace

import pytest

from epub2m4b.tts.xtts import (
    DEFAULT_SPEAKER,
    XTTS_SAFE_MAX_CHARS,
    XTTS_TR_TOKENIZER_LIMIT,
    VOICE_MODE_BUILTIN,
    VOICE_MODE_CLONE,
    XTTSEngine,
    extract_speakers,
)


def test_extract_speakers_uses_public_and_manager_sources_without_duplicates():
    speaker_manager = SimpleNamespace(
        speakers={"Ayse": 0, "Mehmet": 1},
        name_to_id={"Mehmet": 1, DEFAULT_SPEAKER: 2},
    )
    model = SimpleNamespace(speaker_manager=speaker_manager)
    synthesizer = SimpleNamespace(tts_model=model)
    fake_tts = SimpleNamespace(speakers=["Ayse", "Zeynep"], synthesizer=synthesizer)

    assert extract_speakers(fake_tts) == ["Ayse", "Zeynep", "Mehmet", DEFAULT_SPEAKER]


def test_xtts_builtin_mode_does_not_require_reference_audio():
    engine = XTTSEngine(accept_model_license=True, voice_mode=VOICE_MODE_BUILTIN)
    assert engine.reference_audio_required() is False
    assert engine.requested_speaker == DEFAULT_SPEAKER
    assert engine.speed == 1.0


def test_xtts_clone_mode_requires_reference_audio():
    engine = XTTSEngine(accept_model_license=True, voice_mode=VOICE_MODE_CLONE, speed=1.2)
    assert engine.reference_audio_required() is True
    assert engine.speed == 1.2


def test_xtts_rejects_invalid_mode_and_speed():
    with pytest.raises(ValueError, match="Bilinmeyen XTTS ses modu"):
        XTTSEngine(accept_model_license=True, voice_mode="unknown")
    with pytest.raises(ValueError, match="XTTS hiz degeri"):
        XTTSEngine(accept_model_license=True, speed=2.0)


def test_xtts_turkish_chunk_limit_stays_below_upstream_tokenizer_limit():
    assert XTTS_TR_TOKENIZER_LIMIT == 226
    assert XTTS_SAFE_MAX_CHARS == 220
    assert XTTSEngine.info.recommended_max_chars == XTTS_SAFE_MAX_CHARS
    assert XTTSEngine.info.recommended_max_chars < XTTS_TR_TOKENIZER_LIMIT


def test_xtts_synthesize_rejects_oversized_chunk_before_loading_model(tmp_path):
    engine = XTTSEngine(accept_model_license=True)
    oversized = "a" * (XTTS_SAFE_MAX_CHARS + 1)
    with pytest.raises(RuntimeError, match="guvenli siniri asti"):
        engine.synthesize(oversized, tmp_path / "oversized.wav")


def test_xtts_defaults_to_optimized_performance_mode():
    from epub2m4b.tts.xtts import PERFORMANCE_MODE_OPTIMIZED

    engine = XTTSEngine(accept_model_license=True)
    assert engine.performance_mode == PERFORMANCE_MODE_OPTIMIZED


def test_xtts_rejects_invalid_performance_mode():
    with pytest.raises(ValueError, match="performans modu"):
        XTTSEngine(accept_model_license=True, performance_mode="turbo-unknown")


def test_xtts_builtin_conditioning_is_cached():
    class TensorLike:
        def __init__(self):
            self.moves = 0

        def to(self, _device):
            self.moves += 1
            return self

    gpt = TensorLike()
    speaker = TensorLike()
    manager = SimpleNamespace(speakers={DEFAULT_SPEAKER: {"gpt_cond_latent": gpt, "speaker_embedding": speaker}})
    engine = XTTSEngine(accept_model_license=True)
    engine.model = SimpleNamespace(speaker_manager=manager)
    engine.tts = SimpleNamespace(speakers=[DEFAULT_SPEAKER])
    engine.resolved_device = "cuda"
    engine.selected_speaker = DEFAULT_SPEAKER

    first = engine._conditioning_for(None)
    second = engine._conditioning_for(None)

    assert first == second
    assert gpt.moves == 1
    assert speaker.moves == 1


def test_xtts_clone_conditioning_is_computed_once(tmp_path):
    calls = []

    class TensorLike:
        def to(self, _device):
            return self

    def getter(*, audio_path):
        calls.append(tuple(audio_path))
        return TensorLike(), TensorLike()

    ref = tmp_path / "voice.wav"
    ref.write_bytes(b"not-real-audio-but-fingerprint-is-enough")
    engine = XTTSEngine(accept_model_license=True, voice_mode=VOICE_MODE_CLONE)
    engine.model = SimpleNamespace(get_conditioning_latents=getter)
    engine.resolved_device = "cuda"

    engine._conditioning_for(ref)
    engine._conditioning_for(ref)

    assert len(calls) == 1


def test_xtts_optimized_path_calls_low_level_inference_and_writes_wav(tmp_path):
    import numpy as np
    import torch

    calls = []
    gpt = torch.zeros((1, 2, 3))
    speaker = torch.zeros((1, 4, 1))

    class FakeModel:
        config = SimpleNamespace(
            temperature=0.75,
            length_penalty=1.0,
            repetition_penalty=10.0,
            top_k=50,
            top_p=0.85,
        )
        args = SimpleNamespace(output_sample_rate=24000)
        speaker_manager = SimpleNamespace(
            speakers={DEFAULT_SPEAKER: {"gpt_cond_latent": gpt, "speaker_embedding": speaker}}
        )

        def inference(self, text, language, gpt_cond_latent, speaker_embedding, **kwargs):
            calls.append((text, language, kwargs["speed"], kwargs["enable_text_splitting"]))
            assert gpt_cond_latent is gpt
            assert speaker_embedding is speaker
            return {"wav": np.zeros(2400, dtype=np.float32)}

    engine = XTTSEngine(accept_model_license=True, speed=1.1)
    engine.tts = SimpleNamespace(speakers=[DEFAULT_SPEAKER], synthesizer=SimpleNamespace(output_sample_rate=24000))
    engine.model = FakeModel()
    engine.resolved_device = "cpu"
    engine.selected_speaker = DEFAULT_SPEAKER
    output = tmp_path / "optimized.wav"

    artifact = engine.synthesize("Kisa bir Turkce deneme metni.", output)

    assert output.is_file()
    assert artifact.sample_rate == 24000
    assert artifact.duration_seconds == pytest.approx(0.1, abs=0.01)
    assert calls == [("Kisa bir Turkce deneme metni.", "tr", 1.1, False)]


def test_xtts_deepspeed_mode_rebuilds_gpt_inference(monkeypatch):
    import sys
    from types import ModuleType

    from epub2m4b.tts.xtts import PERFORMANCE_MODE_DEEPSPEED

    monkeypatch.setitem(sys.modules, "deepspeed", ModuleType("deepspeed"))
    calls = []

    class FakeGPT:
        def init_gpt_for_inference(self, *, kv_cache, use_deepspeed):
            calls.append((kv_cache, use_deepspeed))

        def eval(self):
            calls.append("eval")

    engine = XTTSEngine(accept_model_license=True, performance_mode=PERFORMANCE_MODE_DEEPSPEED)
    engine.model = SimpleNamespace(gpt=FakeGPT(), args=SimpleNamespace(kv_cache=False))

    assert engine._try_enable_deepspeed() is True
    assert engine.effective_performance_mode == PERFORMANCE_MODE_DEEPSPEED
    assert calls == [(False, True), "eval"]


def test_xtts_deepspeed_mode_still_uses_low_level_inference(tmp_path):
    import numpy as np
    import torch

    from epub2m4b.tts.xtts import PERFORMANCE_MODE_DEEPSPEED

    calls = []
    gpt = torch.zeros((1, 2, 3))
    speaker = torch.zeros((1, 4, 1))

    class FakeModel:
        config = SimpleNamespace(
            temperature=0.75,
            length_penalty=1.0,
            repetition_penalty=10.0,
            top_k=50,
            top_p=0.85,
        )
        args = SimpleNamespace(output_sample_rate=24000)
        speaker_manager = SimpleNamespace(
            speakers={DEFAULT_SPEAKER: {"gpt_cond_latent": gpt, "speaker_embedding": speaker}}
        )

        def inference(self, text, language, gpt_cond_latent, speaker_embedding, **kwargs):
            calls.append((text, language))
            return {"wav": np.zeros(2400, dtype=np.float32)}

    engine = XTTSEngine(accept_model_license=True, performance_mode=PERFORMANCE_MODE_DEEPSPEED)
    engine.tts = SimpleNamespace(speakers=[DEFAULT_SPEAKER], synthesizer=SimpleNamespace(output_sample_rate=24000))
    engine.model = FakeModel()
    engine.resolved_device = "cpu"
    engine.selected_speaker = DEFAULT_SPEAKER
    engine._deepspeed_enabled = True

    artifact = engine.synthesize("DeepSpeed deneme metni.", tmp_path / "deep.wav")

    assert artifact.duration_seconds == pytest.approx(0.1, abs=0.01)
    assert calls == [("DeepSpeed deneme metni.", "tr")]


def test_xtts_parallel_seed_is_stable_and_task_specific():
    from epub2m4b.tts.xtts_parallel import _stable_seed

    a = _stable_seed("task-a", "Merhaba dunya")
    b = _stable_seed("task-a", "Merhaba dunya")
    c = _stable_seed("task-b", "Merhaba dunya")
    assert a == b
    assert a != c


def test_xtts_worker_guard_rechunks_oversized_task_without_pool_failure(monkeypatch, tmp_path):
    import wave

    from epub2m4b.core.models import AudioArtifact
    from epub2m4b.tts import xtts_worker_process as worker

    class FakeEngine:
        def __init__(self):
            self.calls = []

        def synthesize(self, text, output_path, reference_wav=None):
            assert len(text) <= XTTS_SAFE_MAX_CHARS
            self.calls.append(text)
            rate = 8000
            frames = 80
            with wave.open(str(output_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(b"\x00\x00" * frames)
            return AudioArtifact(output_path, frames / rate, rate)

    fake = FakeEngine()
    monkeypatch.setattr(worker, "_ENGINE", fake)
    monkeypatch.setattr(worker, "_REFERENCE_WAV", None)
    monkeypatch.setattr(worker, "_WORKER_LOGS", [])

    output = tmp_path / "guarded.wav"
    artifact = worker._synthesize_guarded("a" * 246, output)

    assert output.is_file()
    assert len(fake.calls) == 2
    assert all(len(text) <= XTTS_SAFE_MAX_CHARS for text in fake.calls)
    assert artifact.sample_rate == 8000
    assert artifact.duration_seconds == pytest.approx(0.02, abs=0.005)
    assert any("savunmaci yeniden-bolme" in line for line in worker._WORKER_LOGS)
