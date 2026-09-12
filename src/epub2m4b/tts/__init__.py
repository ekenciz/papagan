"""TTS package public API.

Do not eagerly import the registry here.  ``python -m epub2m4b.tts.<worker>``
imports this package before the worker module itself; an eager registry import
would load ``core.models`` -> ``core`` -> ``pipeline`` -> ``tts.registry`` and
can leave the registry only partially initialized on Windows subprocess boot.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_engine", "engine_infos"]


def __getattr__(name: str) -> Any:
    if name in {"create_engine", "engine_infos"}:
        from .registry import create_engine, engine_infos

        return {"create_engine": create_engine, "engine_infos": engine_infos}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
