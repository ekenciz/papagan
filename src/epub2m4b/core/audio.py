from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

from .models import BookMetadata, ChapterTiming, QualityPreset


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> tuple[str, str | None]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FFmpegError("FFmpeg bulunamadi. scripts/install_* betigini calistirin veya FFmpeg'i PATH'e ekleyin.")
    return ffmpeg, shutil.which("ffprobe")


def audio_duration(path: Path) -> float:
    _, ffprobe = require_ffmpeg()
    if ffprobe:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            try:
                return float(proc.stdout.strip())
            except ValueError:
                pass
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except (wave.Error, OSError) as exc:
        raise FFmpegError(f"Ses suresi okunamadi: {path}") from exc


def _escape_ffmetadata(value: str) -> str:
    value = value.replace("\\", "\\\\")
    for ch in ("=", ";", "#"):
        value = value.replace(ch, "\\" + ch)
    return value.replace("\n", " ").replace("\r", " ")


def write_ffmetadata(path: Path, metadata: BookMetadata, timings: list[ChapterTiming]) -> None:
    lines = [
        ";FFMETADATA1",
        f"title={_escape_ffmetadata(metadata.title)}",
        f"artist={_escape_ffmetadata(metadata.author)}",
        f"album={_escape_ffmetadata(metadata.title)}",
        "media_type=2",
    ]
    for timing in timings:
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={max(0, timing.start_ms)}",
                f"END={max(timing.start_ms + 1, timing.end_ms)}",
                f"title={_escape_ffmetadata(timing.title)}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_m4b(
    chunk_paths: list[Path],
    timings: list[ChapterTiming],
    metadata: BookMetadata,
    output_path: Path,
    quality: QualityPreset,
    workspace: Path,
    cover_path: Path | None = None,
    log=lambda _msg: None,
) -> None:
    ffmpeg, _ = require_ffmpeg()
    if not chunk_paths:
        raise FFmpegError("Birlestirilecek ses parcasi yok.")

    concat_file = workspace / "concat.txt"
    def ffconcat_quote(item: Path) -> str:
        value = item.resolve().as_posix().replace("'", "'\\''")
        return f"file '{value}'\n"

    concat_file.write_text("".join(ffconcat_quote(p) for p in chunk_paths), encoding="utf-8")
    metadata_file = workspace / "chapters.ffmetadata"
    write_ffmetadata(metadata_file, metadata, timings)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-f",
        "ffmetadata",
        "-i",
        str(metadata_file),
    ]
    if cover_path and cover_path.exists():
        cmd += ["-i", str(cover_path), "-map", "0:a:0", "-map", "2:v:0"]
    else:
        cmd += ["-map", "0:a:0"]

    cmd += [
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        quality.bitrate,
        "-ar",
        str(quality.sample_rate),
    ]
    if cover_path and cover_path.exists():
        cmd += ["-c:v", "mjpeg", "-q:v", "2", "-disposition:v:0", "attached_pic"]
    cmd += ["-movflags", "+faststart", str(output_path)]

    log("FFmpeg M4B birlestirme baslatildi...")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip() or "FFmpeg M4B uretimi basarisiz.")
