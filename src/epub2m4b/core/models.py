from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BookMetadata:
    title: str = "Bilinmeyen Kitap"
    author: str = "Bilinmeyen Yazar"
    language: str = "tr"
    cover_bytes: bytes | None = None
    cover_suffix: str = ".jpg"


@dataclass(slots=True)
class Chapter:
    index: int
    title: str
    text: str
    source_href: str = ""
    toc_listed: bool = False


@dataclass(slots=True)
class TocEntry:
    title: str
    href: str = ""
    chapter_index: int | None = None
    children: list["TocEntry"] = field(default_factory=list)
    source: str = "toc"
    default_selected: bool = True


@dataclass(slots=True)
class ParsedBook:
    metadata: BookMetadata
    chapters: list[Chapter]
    toc: list[TocEntry] = field(default_factory=list)
    has_navigation_toc: bool = False

    def default_selected_chapter_indices(self) -> tuple[int, ...]:
        """Return the safe default narration set.

        When the EPUB has an explicit EPUB3 nav/EPUB2 NCX table of contents,
        only spine documents represented by that navigation are selected by
        default.  If the book has no usable navigation TOC at all, all parsed
        spine chapters stay selected so malformed/minimal EPUBs remain usable.
        """
        if self.has_navigation_toc:
            return tuple(chapter.index for chapter in self.chapters if chapter.toc_listed)
        return tuple(chapter.index for chapter in self.chapters)


@dataclass(slots=True)
class AudioArtifact:
    path: Path
    duration_seconds: float
    sample_rate: int | None = None


@dataclass(slots=True)
class ChapterTiming:
    title: str
    start_ms: int
    end_ms: int


@dataclass(slots=True, frozen=True)
class QualityPreset:
    key: str
    label: str
    bitrate: str
    sample_rate: int


QUALITY_PRESETS: dict[str, QualityPreset] = {
    "low": QualityPreset("low", "Dusuk - 32 kbps AAC / 22.05 kHz", "32k", 22050),
    "standard": QualityPreset("standard", "Standart - 64 kbps AAC / 44.1 kHz", "64k", 44100),
    "high": QualityPreset("high", "Yuksek - 128 kbps AAC / 48 kHz", "128k", 48000),
}


@dataclass(slots=True)
class PipelineOptions:
    epub_path: Path
    output_path: Path
    engine_id: str
    quality_key: str = "standard"
    device: str = "auto"
    reference_wav: Path | None = None
    accept_model_license: bool = True
    voice_consent: bool = False
    keep_work_files: bool = False
    engine_options: dict[str, Any] = field(default_factory=dict)
    selected_chapter_indices: tuple[int, ...] | None = None
