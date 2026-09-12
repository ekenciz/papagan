from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from epub2m4b.core.models import AudioArtifact


@dataclass(frozen=True, slots=True)
class EngineInfo:
    id: str
    name: str
    description: str
    license_name: str
    license_url: str
    commercial_use: bool
    recommended_max_chars: int
    needs_reference_audio: bool = False
    supports_builtin_speakers: bool = False
    supports_reference_audio: bool = False
    supports_speed_control: bool = False
    requires_license_ack: bool = False
    gpu_recommended: bool = True


class TTSEngine(ABC):
    info: EngineInfo

    def __init__(self, device: str = "auto", log=None, **options):
        self.device = device
        self.log = log or (lambda _msg: None)
        self.options = options

    def reference_audio_required(self) -> bool:
        """Return whether this concrete engine configuration needs a reference clip."""
        return self.info.needs_reference_audio

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def synthesize(self, text: str, output_path: Path, reference_wav: Path | None = None) -> AudioArtifact:
        raise NotImplementedError

    def runtime_stats(self) -> dict[str, object]:
        return {"device": self.device}

    def close(self) -> None:
        pass
