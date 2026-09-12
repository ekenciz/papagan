from __future__ import annotations

import re

ABBREVIATIONS = (
    "Dr.", "Doç.", "Prof.", "Sn.", "Bay.", "Bayan.", "örn.", "vb.", "vs.", "bkz.", "No.", "Mad.",
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


def normalize_text(text: str) -> str:
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.replace("\u00a0", " ").splitlines()]
    return "\n\n".join(line for line in lines if line)


def split_sentences(text: str) -> list[str]:
    protected = text
    placeholders: dict[str, str] = {}
    for i, abbr in enumerate(ABBREVIATIONS):
        token = f"__ABBR_{i}__"
        placeholders[token] = abbr
        protected = protected.replace(abbr, abbr.replace(".", token))

    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(protected) if part.strip()]
    restored: list[str] = []
    for part in parts:
        for token, abbr in placeholders.items():
            part = part.replace(abbr.replace(".", token), abbr)
        restored.append(part)
    return restored


def _hard_split(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = max(window.rfind(", "), window.rfind("; "), window.rfind(": "), window.rfind(" "))
        if cut < max_chars // 2:
            cut = max_chars
        piece = remaining[:cut].strip()
        if piece:
            out.append(piece)
        remaining = remaining[cut:].strip()
    if remaining:
        out.append(remaining)
    return out


def chunk_text(text: str, max_chars: int) -> list[str]:
    if max_chars < 80:
        raise ValueError("max_chars en az 80 olmali")
    normalized = normalize_text(text)
    paragraphs = [p.strip() for p in normalized.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        units = [paragraph] if len(paragraph) <= max_chars else split_sentences(paragraph)
        expanded: list[str] = []
        for unit in units:
            expanded.extend(_hard_split(unit, max_chars) if len(unit) > max_chars else [unit])

        for unit in expanded:
            candidate = f"{current} {unit}".strip() if current else unit
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush()
                current = unit
        flush()  # Paragraph sinirinda dogal duraklamayi koru.

    return chunks
