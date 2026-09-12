from __future__ import annotations

import argparse
from pathlib import Path

from .core.epub import parse_epub
from .core.models import PipelineOptions, QUALITY_PRESETS
from .core.pipeline import ConversionPipeline
from .tts.registry import engine_infos
from .tts.xtts import (
    DEFAULT_SPEAKER,
    MAX_SPEED,
    MIN_SPEED,
    PERFORMANCE_MODE_COMPATIBILITY,
    PERFORMANCE_MODE_DEEPSPEED,
    PERFORMANCE_MODE_OPTIMIZED,
    VOICE_MODE_BUILTIN,
    VOICE_MODE_CLONE,
)


def parse_xtts_workers(value: str) -> int:
    text = value.strip().lower()
    if text in {"auto", "otomatik", "0"}:
        return 0
    try:
        count = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("XTTS worker degeri auto veya 1-4 olmali.") from exc
    if count not in {1, 2, 3, 4}:
        raise argparse.ArgumentTypeError("XTTS worker degeri auto veya 1-4 olmali.")
    return count


def parse_chapter_selector(value: str) -> tuple[int, ...]:
    selected: set[int] = set()
    for token in (part.strip() for part in value.split(",")):
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if start <= 0 or end < start:
                raise argparse.ArgumentTypeError(f"Gecersiz bolum araligi: {token}")
            selected.update(range(start, end + 1))
        else:
            index = int(token)
            if index <= 0:
                raise argparse.ArgumentTypeError(f"Bolum numarasi pozitif olmali: {token}")
            selected.add(index)
    if not selected:
        raise argparse.ArgumentTypeError("En az bir bolum numarasi girin.")
    return tuple(sorted(selected))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="epub2m4b-cli", description="EPUB -> M4B yerel TTS araci")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="EPUB metadata ve bolumlerini analiz et")
    analyze.add_argument("epub", type=Path)

    convert = sub.add_parser("convert", help="EPUB dosyasini M4B'ye donustur")
    convert.add_argument("epub", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--engine", choices=[i.id for i in engine_infos()], default="trendyol")
    convert.add_argument("--quality", choices=QUALITY_PRESETS.keys(), default="standard")
    convert.add_argument("--device", default="auto", help="auto, cuda, cuda:0 veya cpu")
    convert.add_argument("--reference-wav", type=Path)
    convert.add_argument(
        "--xtts-voice-mode",
        choices=[VOICE_MODE_BUILTIN, VOICE_MODE_CLONE],
        default=VOICE_MODE_BUILTIN,
        help="XTTS icin hazir speaker veya referans sesten klonlama modu",
    )
    convert.add_argument("--xtts-speaker", default=DEFAULT_SPEAKER, help="XTTS hazir speaker adi")
    convert.add_argument(
        "--xtts-speed",
        type=float,
        default=1.0,
        help=f"XTTS konusma hizi ({MIN_SPEED:.1f}-{MAX_SPEED:.1f})",
    )
    convert.add_argument(
        "--xtts-performance-mode",
        choices=[PERFORMANCE_MODE_OPTIMIZED, PERFORMANCE_MODE_DEEPSPEED, PERFORMANCE_MODE_COMPATIBILITY],
        default=PERFORMANCE_MODE_OPTIMIZED,
        help="XTTS optimize, deneysel DeepSpeed veya klasik TTS.api uyumluluk yolu",
    )
    convert.add_argument(
        "--xtts-workers",
        type=parse_xtts_workers,
        default=0,
        metavar="auto|1|2|3|4",
        help="CUDA'da XTTS worker sayisi; auto 1-4 worker'i olcer ve en hizlisini secer (varsayilan: auto)",
    )
    convert.add_argument("--accept-model-license", action="store_true")
    convert.add_argument("--voice-consent", action="store_true")
    convert.add_argument("--keep-work-files", action="store_true")
    convert.add_argument(
        "--chapters",
        type=parse_chapter_selector,
        help="Yalniz secili EPUB bolumlerini seslendir (ornek: 1,3-5,9)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "analyze":
        book = parse_epub(args.epub)
        print(f"Baslik: {book.metadata.title}")
        print(f"Yazar: {book.metadata.author}")
        print(f"Dil: {book.metadata.language}")
        print(f"Bolum sayisi: {len(book.chapters)}")
        for chapter in book.chapters:
            print(f"{chapter.index:03d}. {chapter.title} ({len(chapter.text)} karakter)")
        return 0

    pipeline = ConversionPipeline(
        log=print,
        progress=lambda done, total, msg: print(f"[{done}/{total}] {msg}"),
    )
    engine_options = {}
    if args.engine == "xtts":
        engine_options = {
            "voice_mode": args.xtts_voice_mode,
            "speaker": args.xtts_speaker,
            "speed": args.xtts_speed,
            "performance_mode": args.xtts_performance_mode,
            "worker_count": args.xtts_workers,
        }
    options = PipelineOptions(
        epub_path=args.epub,
        output_path=args.output,
        engine_id=args.engine,
        quality_key=args.quality,
        device=args.device,
        reference_wav=args.reference_wav,
        accept_model_license=args.accept_model_license,
        voice_consent=args.voice_consent,
        keep_work_files=args.keep_work_files,
        engine_options=engine_options,
        selected_chapter_indices=args.chapters,
    )
    pipeline.run(options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
