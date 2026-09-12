from pathlib import Path
from zipfile import ZipFile

from epub2m4b.core.epub import parse_epub


def make_epub(path: Path) -> None:
    container = '''<?xml version="1.0"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
    </container>'''
    opf = '''<?xml version="1.0" encoding="utf-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
        <dc:title>Deneme Kitabı</dc:title>
        <dc:creator>Ali Yazar</dc:creator>
        <dc:language>tr</dc:language>
      </metadata>
      <manifest>
        <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
        <item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
        <item id="cover" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>
      </manifest>
      <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
    </package>'''
    c1 = "<html><head><title>Giriş</title></head><body><h1>Giriş</h1><p>Bu bölüm yeterince uzun bir test paragrafıdır.</p></body></html>"
    c2 = "<html><body><h2>İkinci Bölüm</h2><p>İkinci bölümde de seslendirilebilir Türkçe metin bulunur.</p></body></html>"
    with ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c1.xhtml", c1)
        zf.writestr("OEBPS/c2.xhtml", c2)
        zf.writestr("OEBPS/cover.jpg", b"fake-jpeg")


def test_parse_epub_reads_spine_metadata_and_cover(tmp_path):
    path = tmp_path / "book.epub"
    make_epub(path)
    book = parse_epub(path)
    assert book.metadata.title == "Deneme Kitabı"
    assert book.metadata.author == "Ali Yazar"
    assert book.metadata.language == "tr"
    assert book.metadata.cover_bytes == b"fake-jpeg"
    assert [chapter.title for chapter in book.chapters] == ["Giriş", "İkinci Bölüm"]
    assert "test paragrafıdır" in book.chapters[0].text
    assert [entry.title for entry in book.toc] == ["Giriş", "İkinci Bölüm"]
    assert [entry.chapter_index for entry in book.toc] == [1, 2]


def test_parse_epub3_navigation_toc_and_maps_nested_entries(tmp_path):
    path = tmp_path / "toc-book.epub"
    container = '''<?xml version="1.0"?>
    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
    </container>'''
    opf = '''<?xml version="1.0" encoding="utf-8"?>
    <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>TOC</dc:title></metadata>
      <manifest>
        <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
        <item id="c1" href="text/c1.xhtml" media-type="application/xhtml+xml"/>
        <item id="c2" href="text/c2.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
    </package>'''
    nav = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
    <body><nav epub:type="toc"><ol>
      <li><a href="text/c1.xhtml">Kısım Bir</a>
        <ol><li><a href="text/c2.xhtml#start">İkinci Alt Bölüm</a></li></ol>
      </li>
    </ol></nav></body></html>'''
    c1 = "<html><body><h1>Bir</h1><p>Birinci bölüm yeterince uzun bir test metnidir.</p></body></html>"
    c2 = "<html><body><h1 id='start'>İki</h1><p>İkinci bölüm yeterince uzun bir test metnidir.</p></body></html>"
    with ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/text/c1.xhtml", c1)
        zf.writestr("OEBPS/text/c2.xhtml", c2)

    book = parse_epub(path)
    assert len(book.toc) == 1
    assert book.toc[0].title == "Kısım Bir"
    assert book.toc[0].chapter_index == 1
    assert book.toc[0].children[0].title == "İkinci Alt Bölüm"
    assert book.toc[0].children[0].chapter_index == 2


def test_parse_epub2_ncx_toc(tmp_path):
    path = tmp_path / "ncx-book.epub"
    container = '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
      <rootfiles><rootfile full-path="OPS/book.opf" media-type="application/oebps-package+xml"/></rootfiles>
    </container>'''
    opf = '''<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>NCX Kitap</dc:title></metadata>
      <manifest>
        <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="c1" href="text/c1.xhtml" media-type="application/xhtml+xml"/>
      </manifest>
      <spine toc="ncx"><itemref idref="c1"/></spine>
    </package>'''
    ncx = '''<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
      <navMap><navPoint id="n1"><navLabel><text>Başlangıç</text></navLabel>
      <content src="text/c1.xhtml#top"/></navPoint></navMap>
    </ncx>'''
    c1 = "<html><body><h1 id='top'>Başlangıç</h1><p>NCX ile eşlenecek yeterince uzun bir Türkçe test metnidir.</p></body></html>"
    with ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OPS/book.opf", opf)
        zf.writestr("OPS/toc.ncx", ncx)
        zf.writestr("OPS/text/c1.xhtml", c1)

    book = parse_epub(path)
    assert book.toc[0].title == "Başlangıç"
    assert book.toc[0].chapter_index == 1
