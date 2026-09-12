from __future__ import annotations

from pathlib import Path

from epub2m4b.core.models import AudioArtifact
from epub2m4b.hf_compat import install_windows_hf_symlink_fallback

from .base import EngineInfo, TTSEngine


class MMSTurkishEngine(TTSEngine):
    info = EngineInfo(
        id="mms",
        name="Facebook MMS-TTS Turkish",
        description="Meta MMS VITS tabanli hafif Turkce TTS checkpoint'i.",
        license_name="CC-BY-NC-4.0",
        license_url="https://huggingface.co/facebook/mms-tts-tur",
        commercial_use=False,
        recommended_max_chars=320,
        requires_license_ack=True,
        gpu_recommended=False,
    )

    def __init__(self, device: str = "auto", accept_model_license: bool = False, **options):
        super().__init__(device, **options)
        self.accept_model_license = accept_model_license
        self.model = None
        self.tokenizer = None
        self.resolved_device = device

    def load(self) -> None:
        if not self.accept_model_license:
            raise RuntimeError("MMS-TTS CC-BY-NC-4.0 lisansi kabul edilmeden model kullanilamaz.")
        try:
            import torch
            from transformers import AutoTokenizer, VitsModel
        except ImportError as exc:
            raise RuntimeError("MMS motoru icin 'transformers', PyTorch ve soundfile kurulmalidir.") from exc

        if install_windows_hf_symlink_fallback():
            self.log("Windows Hugging Face onbellegi: yetkisiz symlink yerine guvenli dosya kopyalama modu etkin.")

        if self.device == "auto":
            self.resolved_device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.resolved_device = self.device
        self.tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-tur")
        self.model = VitsModel.from_pretrained("facebook/mms-tts-tur").to(self.resolved_device)
        self.model.eval()

    def synthesize(self, text: str, output_path: Path, reference_wav: Path | None = None) -> AudioArtifact:
        if self.model is None or self.tokenizer is None:
            self.load()
        import soundfile as sf
        import torch

        inputs = self.tokenizer(text, return_tensors="pt")
        inputs = {k: v.to(self.resolved_device) for k, v in inputs.items()}
        with torch.inference_mode():
            waveform = self.model(**inputs).waveform.squeeze().detach().cpu().float().numpy()
        sample_rate = int(self.model.config.sampling_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), waveform, sample_rate)
        return AudioArtifact(output_path, len(waveform) / float(sample_rate), sample_rate)

    def close(self) -> None:
        self.model = None
        self.tokenizer = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
