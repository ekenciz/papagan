from epub2m4b.core.audio import write_ffmetadata
from epub2m4b.core.models import BookMetadata, ChapterTiming


def test_ffmetadata_contains_chapters(tmp_path):
    out = tmp_path / "chapters.ffmetadata"
    write_ffmetadata(
        out,
        BookMetadata(title="Kitap #1", author="Yazar"),
        [
            ChapterTiming("Giriş", 0, 12345),
            ChapterTiming("Bölüm 2", 12345, 30000),
        ],
    )
    text = out.read_text(encoding="utf-8")
    assert text.startswith(";FFMETADATA1")
    assert "title=Kitap \\#1" in text
    assert text.count("[CHAPTER]") == 2
    assert "START=12345" in text
    assert "title=Bölüm 2" in text
