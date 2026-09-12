from __future__ import annotations

from pathlib import Path

from epub2m4b.core.models import AudioArtifact
from epub2m4b.hf_compat import install_windows_hf_symlink_fallback

from .base import EngineInfo, TTSEngine


class TrendyolVoxCPMEngine(TTSEngine):
    info = EngineInfo(
        id="trendyol",
        name="Trendyol-TTS (VoxCPM2)",
        description="Turkce icin VoxCPM2 tabanli Trendyol LoRA/merged checkpoint.",
        license_name="MIT model metadata + Apache-2.0 VoxCPM2",
        license_url="https://huggingface.co/Trendyol/Trendyol-TTS",
        commercial_use=True,
        recommended_max_chars=760,
        gpu_recommended=True,
    )

    def __init__(self, device: str = "auto", **options):
        super().__init__(device, **options)
        self.model = None

    def load(self) -> None:
        try:
            from voxcpm import VoxCPM
        except ImportError as exc:
            raise RuntimeError("Trendyol motoru icin 'voxcpm' paketi kurulu degil.") from exc

        # huggingface_hub < 1.9 can incorrectly attempt symlink creation on
        # Windows even when the account lacks SeCreateSymbolicLinkPrivilege.
        # Patch only that exact WinError 1314 path so existing downloaded blobs
        # are reused instead of forcing a multi-GB re-download.
        if install_windows_hf_symlink_fallback():
            self.log("Windows Hugging Face onbellegi: yetkisiz symlink yerine guvenli dosya kopyalama modu etkin.")

        optimize = self.device.startswith("cuda") if self.device != "auto" else True
        self.model = VoxCPM.from_pretrained(
            hf_model_id="Trendyol/Trendyol-TTS",
            load_denoiser=False,
            optimize=optimize,
            device=self.device,
        )

    def synthesize(self, text: str, output_path: Path, reference_wav: Path | None = None) -> AudioArtifact:
        if self.model is None:
            self.load()
        import soundfile as sf

        cfg_value = float(self.options.get("cfg_value", 2.0))
        inference_timesteps = int(self.options.get("inference_timesteps", 16))
        wav = self.model.generate(
            text=text,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            max_len=4096,
            normalize=True,
            denoise=False,
        )
        sample_rate = int(self.model.tts_model.sample_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), wav, sample_rate)
        return AudioArtifact(output_path, len(wav) / float(sample_rate), sample_rate)

    def close(self) -> None:
        self.model = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
