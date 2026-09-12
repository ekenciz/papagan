from __future__ import annotations

from .base import EngineInfo, TTSEngine
from .mms import MMSTurkishEngine
from .trendyol import TrendyolVoxCPMEngine
from .xtts import XTTSEngine

ENGINE_CLASSES: dict[str, type[TTSEngine]] = {
    TrendyolVoxCPMEngine.info.id: TrendyolVoxCPMEngine,
    XTTSEngine.info.id: XTTSEngine,
    MMSTurkishEngine.info.id: MMSTurkishEngine,
}


def engine_infos() -> list[EngineInfo]:
    return [cls.info for cls in ENGINE_CLASSES.values()]


def create_engine(engine_id: str, **kwargs) -> TTSEngine:
    try:
        cls = ENGINE_CLASSES[engine_id]
    except KeyError as exc:
        raise ValueError(f"Bilinmeyen TTS motoru: {engine_id}") from exc
    return cls(**kwargs)
