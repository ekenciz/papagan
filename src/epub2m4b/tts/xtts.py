from __future__ import annotations

import os
import time
import warnings
from pathlib import Path
from typing import Any

from epub2m4b.core.models import AudioArtifact

from .base import EngineInfo, TTSEngine

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER = "Chandra MacFarland"
VOICE_MODE_BUILTIN = "builtin"
VOICE_MODE_CLONE = "clone"
VOICE_MODES = {VOICE_MODE_BUILTIN, VOICE_MODE_CLONE}
PERFORMANCE_MODE_OPTIMIZED = "optimized"
PERFORMANCE_MODE_DEEPSPEED = "deepspeed"
PERFORMANCE_MODE_COMPATIBILITY = "compatibility"
PERFORMANCE_MODES = {
    PERFORMANCE_MODE_OPTIMIZED,
    PERFORMANCE_MODE_DEEPSPEED,
    PERFORMANCE_MODE_COMPATIBILITY,
}
MIN_SPEED = 0.7
MAX_SPEED = 1.6
DEFAULT_SPEED = 1.0
XTTS_TR_TOKENIZER_LIMIT = 226
XTTS_SAFE_MAX_CHARS = 220


class FastPathUnavailable(RuntimeError):
    """Raised only when the low-level XTTS API cannot be used safely."""


def extract_speakers(tts: Any) -> list[str]:
    names: list[str] = []

    raw_speakers = getattr(tts, "speakers", None)
    if isinstance(raw_speakers, dict):
        names.extend(str(key) for key in raw_speakers)
    elif isinstance(raw_speakers, (list, tuple, set)):
        names.extend(str(value) for value in raw_speakers)
    elif raw_speakers is not None and not isinstance(raw_speakers, str):
        try:
            names.extend(str(value) for value in raw_speakers)
        except TypeError:
            pass

    tts_model = getattr(getattr(tts, "synthesizer", None), "tts_model", None)
    speaker_manager = getattr(tts_model, "speaker_manager", None)
    if speaker_manager is not None:
        manager_speakers = getattr(speaker_manager, "speakers", None)
        if isinstance(manager_speakers, dict):
            names.extend(str(key) for key in manager_speakers)
        elif isinstance(manager_speakers, (list, tuple, set)):
            names.extend(str(value) for value in manager_speakers)

        name_to_id = getattr(speaker_manager, "name_to_id", None)
        if isinstance(name_to_id, dict):
            names.extend(str(key) for key in name_to_id)
        elif name_to_id is not None and not isinstance(name_to_id, str):
            try:
                names.extend(str(value) for value in name_to_id)
            except TypeError:
                pass

    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean = (name or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            unique.append(clean)
    return unique


def _speaker_latents(entry: Any) -> tuple[Any, Any]:
    """Read built-in XTTS conditioning tensors across compatible Coqui layouts."""

    if isinstance(entry, dict):
        gpt = entry.get("gpt_conditioning_latents")
        if gpt is None:
            gpt = entry.get("gpt_cond_latent")
        speaker = entry.get("speaker_embedding")
        if gpt is not None and speaker is not None:
            return gpt, speaker
        values = list(entry.values())
        if len(values) >= 2:
            return values[0], values[1]
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return entry[0], entry[1]
    raise FastPathUnavailable("XTTS speaker conditioning verisi okunamadi.")


class XTTSEngine(TTSEngine):
    info = EngineInfo(
        id="xtts",
        name="Coqui XTTS v2 (TR)",
        description=(
            "Turkce XTTS v2: hazir speaker veya izinli referans ses; optimize inference, "
            "conditioning cache ve ayarlanabilir konusma hizi."
        ),
        license_name="Coqui Public Model License (CPML) - non-commercial",
        license_url="https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt",
        commercial_use=False,
        recommended_max_chars=XTTS_SAFE_MAX_CHARS,
        needs_reference_audio=False,
        supports_builtin_speakers=True,
        supports_reference_audio=True,
        supports_speed_control=True,
        requires_license_ack=True,
        gpu_recommended=True,
    )

    def __init__(self, device: str = "auto", accept_model_license: bool = True, **options):
        super().__init__(device, **options)
        self.accept_model_license = accept_model_license
        self.voice_mode = str(options.get("voice_mode", VOICE_MODE_BUILTIN)).strip().lower()
        if self.voice_mode not in VOICE_MODES:
            raise ValueError(f"Bilinmeyen XTTS ses modu: {self.voice_mode}")

        requested_speaker = options.get("speaker")
        self.requested_speaker = str(requested_speaker).strip() if requested_speaker else DEFAULT_SPEAKER

        try:
            self.speed = float(options.get("speed", DEFAULT_SPEED))
        except (TypeError, ValueError) as exc:
            raise ValueError("XTTS hiz degeri sayisal olmalidir.") from exc
        if not MIN_SPEED <= self.speed <= MAX_SPEED:
            raise ValueError(f"XTTS hiz degeri {MIN_SPEED:.1f}x ile {MAX_SPEED:.1f}x arasinda olmalidir.")

        self.performance_mode = str(
            options.get("performance_mode", PERFORMANCE_MODE_OPTIMIZED)
        ).strip().lower()
        if self.performance_mode not in PERFORMANCE_MODES:
            raise ValueError(f"Bilinmeyen XTTS performans modu: {self.performance_mode}")

        self.tts = None
        self.model = None
        self.resolved_device = device
        self.selected_speaker: str | None = None
        self._gpt_cond_latent = None
        self._speaker_embedding = None
        self._conditioning_key: tuple[Any, ...] | None = None
        self._fast_path_logged = False
        self._compat_fallback_logged = False
        self._deepspeed_enabled = False
        self._deepspeed_fallback_reason: str | None = None
        self._nvml_handle = None
        self._last_runtime_stats: dict[str, Any] = {}
        self._last_runtime_stats_at = 0.0

    def reference_audio_required(self) -> bool:
        return self.voice_mode == VOICE_MODE_CLONE

    def load(self) -> None:
        if not self.accept_model_license:
            raise RuntimeError("XTTS v2 CPML lisansi kullanici tarafindan kabul edilmeden model indirilemez.")
        os.environ["COQUI_TOS_AGREED"] = "1"
        try:
            import torch
        except Exception as exc:
            raise RuntimeError(
                f"PyTorch yuklenemedi: {type(exc).__name__}: {exc}. "
                "GUI'deki 'Bagimliliklari Kur/Onar' dugmesini calistirin."
            ) from exc

        warnings.filterwarnings(
            "ignore",
            message=r"`torch\.jit\.script` is deprecated\..*",
            category=FutureWarning,
            module=r"torch\.jit\._script",
        )
        try:
            from TTS.api import TTS
        except Exception as exc:
            raise RuntimeError(
                "coqui-tts kurulu gorunuyor ancak TTS.api yuklenemedi: "
                f"{type(exc).__name__}: {exc}. GUI'deki 'Bagimliliklari Kur/Onar' dugmesini calistirin."
            ) from exc

        if self.device == "auto":
            self.resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.resolved_device = self.device
        if str(self.resolved_device).startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA secildi ancak PyTorch CUDA'yi kullanilabilir gormuyor.")

        if str(self.resolved_device).startswith("cuda"):
            try:
                torch.set_float32_matmul_precision("high")
            except Exception:
                pass
            try:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
            except Exception:
                pass

        self.log(f"XTTS v2 yukleniyor: {self.resolved_device}")
        self.tts = TTS(MODEL_NAME).to(self.resolved_device)
        self.model = getattr(getattr(self.tts, "synthesizer", None), "tts_model", None)

        if self.voice_mode == VOICE_MODE_BUILTIN:
            self.selected_speaker = self._resolve_speaker(self.requested_speaker)
            self.log(f"XTTS hazir speaker: {self.selected_speaker}; hiz: {self.speed:.2f}x")
        else:
            self.selected_speaker = None
            self.log(f"XTTS referans ses klonlama modu; hiz: {self.speed:.2f}x")

        if self.performance_mode == PERFORMANCE_MODE_DEEPSPEED and self.model is not None:
            if self._try_enable_deepspeed():
                self.log(
                    "XTTS performans modu: DeepSpeed (deneysel) + low-level inference + conditioning cache."
                )
            else:
                self.performance_mode = PERFORMANCE_MODE_OPTIMIZED
                self.log(
                    "XTTS DeepSpeed etkinlestirilemedi; optimize moda geri donuldu"
                    + (f" ({self._deepspeed_fallback_reason})." if self._deepspeed_fallback_reason else ".")
                )
        elif self.performance_mode == PERFORMANCE_MODE_OPTIMIZED and self.model is not None:
            self.log("XTTS performans modu: optimize (low-level inference + conditioning cache + TF32).")
        elif self.performance_mode == PERFORMANCE_MODE_COMPATIBILITY:
            self.log("XTTS performans modu: uyumluluk (TTS.api tts_to_file).")
        else:
            self.log("XTTS low-level model API bulunamadi; uyumluluk yoluna gecilecek.")

    def _try_enable_deepspeed(self) -> bool:
        """Rebuild XTTS GPT inference with DeepSpeed kernel injection when available.

        Coqui's ``load_checkpoint(..., use_deepspeed=True)`` ultimately calls
        ``gpt.init_gpt_for_inference(..., use_deepspeed=True)``.  The public TTS
        wrapper has already loaded the checkpoint by the time we get here, so
        re-initialising only the inference wrapper avoids downloading/loading a
        second checkpoint while still using the same supported XTTS path.
        """

        try:
            import deepspeed  # noqa: F401
        except Exception as exc:
            self._deepspeed_fallback_reason = f"deepspeed yuklu degil: {type(exc).__name__}: {exc}"
            return False
        try:
            gpt = getattr(self.model, "gpt", None)
            init = getattr(gpt, "init_gpt_for_inference", None)
            if not callable(init):
                raise FastPathUnavailable("XTTS GPT DeepSpeed init API bulunamadi")
            kv_cache = bool(getattr(getattr(self.model, "args", None), "kv_cache", True))
            init(kv_cache=kv_cache, use_deepspeed=True)
            eval_fn = getattr(gpt, "eval", None)
            if callable(eval_fn):
                eval_fn()
            self._deepspeed_enabled = True
            self._deepspeed_fallback_reason = None
            return True
        except Exception as exc:
            self._deepspeed_enabled = False
            self._deepspeed_fallback_reason = f"{type(exc).__name__}: {exc}"
            return False

    @property
    def effective_performance_mode(self) -> str:
        if self._deepspeed_enabled:
            return PERFORMANCE_MODE_DEEPSPEED
        return self.performance_mode

    def list_speakers(self) -> list[str]:
        if self.tts is None:
            self.load()
        return extract_speakers(self.tts)

    def _resolve_speaker(self, requested: str | None) -> str:
        speakers = extract_speakers(self.tts)
        if requested:
            if speakers and requested not in speakers:
                if requested == DEFAULT_SPEAKER:
                    self.log(
                        f"Onerilen XTTS speaker '{DEFAULT_SPEAKER}' listede yok; "
                        f"ilk speaker '{speakers[0]}' kullaniliyor."
                    )
                    return speakers[0]
                if DEFAULT_SPEAKER in speakers:
                    self.log(
                        f"XTTS speaker '{requested}' bulunamadi; varsayilan '{DEFAULT_SPEAKER}' kullaniliyor."
                    )
                    return DEFAULT_SPEAKER
                raise RuntimeError(f"XTTS speaker bulunamadi: {requested}")
            return requested
        if DEFAULT_SPEAKER in speakers:
            return DEFAULT_SPEAKER
        if speakers:
            return speakers[0]
        return DEFAULT_SPEAKER

    def _conditioning_for(self, reference_wav: Path | None) -> tuple[Any, Any]:
        if self.model is None:
            raise FastPathUnavailable("XTTS low-level model API bulunamadi.")

        if self.voice_mode == VOICE_MODE_BUILTIN:
            if self.selected_speaker is None:
                self.selected_speaker = self._resolve_speaker(self.requested_speaker)
            key = ("builtin", self.selected_speaker)
            if self._conditioning_key == key and self._gpt_cond_latent is not None:
                return self._gpt_cond_latent, self._speaker_embedding
            manager = getattr(self.model, "speaker_manager", None)
            speakers = getattr(manager, "speakers", None)
            if not isinstance(speakers, dict) or self.selected_speaker not in speakers:
                raise FastPathUnavailable("XTTS built-in speaker cache API bulunamadi.")
            gpt, speaker = _speaker_latents(speakers[self.selected_speaker])
        else:
            if reference_wav is None or not reference_wav.is_file():
                raise RuntimeError("XTTS voice cloning modu icin gecerli bir referans ses dosyasi secilmelidir.")
            stat = reference_wav.stat()
            key = ("clone", str(reference_wav.resolve()), stat.st_size, stat.st_mtime_ns)
            if self._conditioning_key == key and self._gpt_cond_latent is not None:
                return self._gpt_cond_latent, self._speaker_embedding
            getter = getattr(self.model, "get_conditioning_latents", None)
            if not callable(getter):
                raise FastPathUnavailable("XTTS conditioning latent API bulunamadi.")
            self.log("XTTS referans ses conditioning verisi bir kez hesaplaniyor ve kitap boyunca cache'lenecek...")
            gpt, speaker = getter(audio_path=[str(reference_wav)])

        target = self.resolved_device
        if hasattr(gpt, "to"):
            gpt = gpt.to(target)
        if hasattr(speaker, "to"):
            speaker = speaker.to(target)
        self._gpt_cond_latent = gpt
        self._speaker_embedding = speaker
        self._conditioning_key = key
        return gpt, speaker

    def _inference_settings(self) -> dict[str, Any]:
        config = getattr(self.model, "config", None)
        settings: dict[str, Any] = {
            "speed": self.speed,
            "enable_text_splitting": False,
        }
        defaults = {
            "temperature": 0.75,
            "length_penalty": 1.0,
            "repetition_penalty": 10.0,
            "top_k": 50,
            "top_p": 0.85,
        }
        for name, fallback in defaults.items():
            settings[name] = getattr(config, name, fallback)
        return settings

    def _output_sample_rate(self) -> int:
        candidates = [
            getattr(getattr(self.model, "args", None), "output_sample_rate", None),
            getattr(getattr(getattr(self.model, "config", None), "audio", None), "output_sample_rate", None),
            getattr(getattr(self.tts, "synthesizer", None), "output_sample_rate", None),
        ]
        for value in candidates:
            try:
                rate = int(value)
            except (TypeError, ValueError):
                continue
            if rate > 0:
                return rate
        return 24000

    def _synthesize_optimized(self, text: str, output_path: Path, reference_wav: Path | None) -> AudioArtifact:
        if self.model is None:
            raise FastPathUnavailable("XTTS low-level model API bulunamadi.")
        inference = getattr(self.model, "inference", None)
        if not callable(inference):
            raise FastPathUnavailable("XTTS low-level inference API bulunamadi.")

        import numpy as np
        import soundfile as sf
        import torch

        gpt_cond_latent, speaker_embedding = self._conditioning_for(reference_wav)
        if not self._fast_path_logged:
            self.log("XTTS optimize inference etkin: speaker conditioning yeniden hesaplanmayacak.")
            self._fast_path_logged = True

        with torch.inference_mode():
            result = inference(
                text,
                "tr",
                gpt_cond_latent,
                speaker_embedding,
                **self._inference_settings(),
            )
        wav = result.get("wav") if isinstance(result, dict) else None
        if wav is None:
            raise RuntimeError("XTTS inference cikisinda 'wav' bulunamadi.")
        if hasattr(wav, "detach"):
            wav = wav.detach().float().cpu().numpy()
        array = np.asarray(wav, dtype=np.float32).squeeze()
        if array.ndim != 1 or array.size == 0:
            raise RuntimeError("XTTS gecersiz ses dizisi uretti.")
        sample_rate = self._output_sample_rate()
        sf.write(str(output_path), array, sample_rate, subtype="PCM_16")
        return AudioArtifact(output_path, float(array.size / sample_rate), sample_rate)

    def _synthesize_compatibility(self, text: str, output_path: Path, reference_wav: Path | None) -> AudioArtifact:
        import soundfile as sf

        kwargs: dict[str, Any] = {
            "text": text,
            "language": "tr",
            "file_path": str(output_path),
            "speed": self.speed,
            "split_sentences": False,
        }
        if self.voice_mode == VOICE_MODE_CLONE:
            if reference_wav is None or not reference_wav.is_file():
                raise RuntimeError("XTTS voice cloning modu icin gecerli bir referans ses dosyasi secilmelidir.")
            kwargs["speaker_wav"] = str(reference_wav)
        else:
            if self.selected_speaker is None:
                self.selected_speaker = self._resolve_speaker(self.requested_speaker)
            kwargs["speaker"] = self.selected_speaker
        self.tts.tts_to_file(**kwargs)
        info = sf.info(str(output_path))
        return AudioArtifact(output_path, float(info.duration), int(info.samplerate))

    def synthesize(self, text: str, output_path: Path, reference_wav: Path | None = None) -> AudioArtifact:
        if len(text) > XTTS_SAFE_MAX_CHARS:
            raise RuntimeError(
                "XTTS Turkce metin parcasi guvenli siniri asti: "
                f"{len(text)} karakter > {XTTS_SAFE_MAX_CHARS}."
            )
        if self.tts is None:
            self.load()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self.performance_mode in {PERFORMANCE_MODE_OPTIMIZED, PERFORMANCE_MODE_DEEPSPEED}:
            try:
                return self._synthesize_optimized(text, output_path, reference_wav)
            except FastPathUnavailable as exc:
                if not self._compat_fallback_logged:
                    self.log(f"XTTS optimize yol kullanilamadi ({exc}); uyumluluk yoluna geciliyor.")
                    self._compat_fallback_logged = True
        return self._synthesize_compatibility(text, output_path, reference_wav)

    def runtime_stats(self) -> dict[str, Any]:
        now = time.monotonic()
        if now - self._last_runtime_stats_at < 1.0 and self._last_runtime_stats:
            return dict(self._last_runtime_stats)
        stats: dict[str, Any] = {"device": self.resolved_device}
        if not str(self.resolved_device).startswith("cuda"):
            self._last_runtime_stats = stats
            self._last_runtime_stats_at = now
            return dict(stats)
        try:
            import torch

            index = 0
            if ":" in str(self.resolved_device):
                index = int(str(self.resolved_device).split(":", 1)[1])
            stats["gpu_name"] = torch.cuda.get_device_name(index)
            stats["vram_allocated_gb"] = round(torch.cuda.memory_allocated(index) / (1024**3), 2)
            stats["vram_reserved_gb"] = round(torch.cuda.memory_reserved(index) / (1024**3), 2)
            stats["vram_total_gb"] = round(torch.cuda.get_device_properties(index).total_memory / (1024**3), 2)
        except Exception:
            pass
        try:
            import pynvml

            if self._nvml_handle is None:
                pynvml.nvmlInit()
                index = 0
                if ":" in str(self.resolved_device):
                    index = int(str(self.resolved_device).split(":", 1)[1])
                self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            util = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
            stats["gpu_util_percent"] = int(util.gpu)
            stats["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(self._nvml_handle) / 1000.0)
            memory = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
            stats["vram_device_used_gb"] = round(memory.used / (1024**3), 2)
            stats["vram_device_total_gb"] = round(memory.total / (1024**3), 2)
        except Exception:
            pass
        stats["effective_performance_mode"] = self.effective_performance_mode
        self._last_runtime_stats = stats
        self._last_runtime_stats_at = now
        return dict(stats)

    def close(self) -> None:
        self.tts = None
        self.model = None
        self.selected_speaker = None
        self._gpt_cond_latent = None
        self._speaker_embedding = None
        self._conditioning_key = None
        self._nvml_handle = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
