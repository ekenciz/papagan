"""Core package public API.

Keep this module deliberately lightweight.  XTTS subprocess workers import
``epub2m4b.core.models`` while the TTS registry imports the pipeline.  Eagerly
importing ``ConversionPipeline`` here therefore creates a circular import when
Python boots a worker with ``python -m epub2m4b.tts.xtts_worker_process``.

Public names are preserved through PEP 562 lazy attributes so existing callers
can still use ``from epub2m4b.core import ConversionPipeline`` without pulling
the whole pipeline into every submodule import.
"""

from __future__ import annotations

from typing import Any

__all__ = ["parse_epub", "PipelineOptions", "QUALITY_PRESETS", "ConversionPipeline"]


def __getattr__(name: str) -> Any:
    if name == "parse_epub":
        from .epub import parse_epub

        return parse_epub
    if name in {"PipelineOptions", "QUALITY_PRESETS"}:
        from .models import PipelineOptions, QUALITY_PRESETS

        return {"PipelineOptions": PipelineOptions, "QUALITY_PRESETS": QUALITY_PRESETS}[name]
    if name == "ConversionPipeline":
        from .pipeline import ConversionPipeline

        return ConversionPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
