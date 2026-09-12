from epub2m4b.core.chunker import chunk_text, enforce_chunk_limit, split_sentences
from epub2m4b.tts.xtts import XTTS_SAFE_MAX_CHARS


def test_chunk_text_respects_limit():
    text = (
        "Bu birinci cümledir. Bu ikinci cümledir ve biraz daha uzundur.\n\n"
        "Yeni paragraf burada başlıyor. Ardından başka bir cümle geliyor."
    )
    chunks = chunk_text(text, 80)
    assert chunks
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert "Yeni paragraf" in " ".join(chunks)


def test_common_turkish_abbreviation_is_not_split():
    sentences = split_sentences("Prof. Ahmet bugün geldi. Sonra konuşma başladı.")
    assert sentences == ["Prof. Ahmet bugün geldi.", "Sonra konuşma başladı."]


def test_long_sentence_hard_split():
    text = " ".join(["kelime"] * 100)
    chunks = chunk_text(text, 100)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_xtts_safe_limit_splits_long_turkish_paragraphs():
    text = (
        "Christie'nin orta çağ ve rönesans el yazmaları hakkında uzun bir açıklaması vardır. "
        "Bu açıklama kalem, mürekkep ve yazı araçlarının gelişimini ayrıntılı biçimde anlatır. "
        "Ayrıca tarihsel örnekler, koleksiyonlar ve farklı dönemlere ait yazım alışkanlıkları "
        "birkaç uzun cümle boyunca sürdürülür. "
    ) * 4
    chunks = chunk_text(text, XTTS_SAFE_MAX_CHARS)
    assert len(chunks) > 1
    assert all(len(chunk) <= XTTS_SAFE_MAX_CHARS for chunk in chunks)


def test_enforce_chunk_limit_repairs_oversized_input():
    chunks = ["a" * 246, "kisa"]
    repaired = enforce_chunk_limit(chunks, XTTS_SAFE_MAX_CHARS)
    assert len(repaired) == 3
    assert all(len(chunk) <= XTTS_SAFE_MAX_CHARS for chunk in repaired)
    assert "".join(repaired[:2]) == "a" * 246
