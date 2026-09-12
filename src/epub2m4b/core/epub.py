from __future__ import annotations

import mimetypes
import posixpath
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

from .models import BookMetadata, Chapter, ParsedBook, TocEntry

CONTAINER_PATH = "META-INF/container.xml"
NS_CONTAINER = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
DC_NS = "http://purl.org/dc/elements/1.1/"


class EpubParseError(RuntimeError):
    pass


def _text(elem: ET.Element | None, fallback: str) -> str:
    if elem is None or not elem.text:
        return fallback
    value = re.sub(r"\s+", " ", elem.text).strip()
    return value or fallback


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _resolve(base: str, href: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href))


def _resolve_target(base: str, href: str) -> str:
    """Resolve a navigation href to a canonical EPUB-internal path.

    Fragments are kept for UI/debugging, while chapter mapping intentionally
    operates on the document path because the v0.1 pipeline synthesizes one
    spine document as one selectable audio unit.
    """

    parts = urlsplit(href or "")
    raw_path = unquote(parts.path)
    path = _resolve(base, raw_path) if raw_path else posixpath.normpath(base)
    fragment = unquote(parts.fragment)
    return f"{path}#{fragment}" if fragment else path


def _without_fragment(href: str) -> str:
    return href.split("#", 1)[0]


def _find_metadata(root: ET.Element, name: str) -> ET.Element | None:
    for elem in root.iter():
        if _local(elem.tag) == name and (elem.tag.startswith("{" + DC_NS + "}") or _local(elem.tag) == name):
            return elem
    return None


def _extract_cover(zf: zipfile.ZipFile, opf_path: str, root: ET.Element, manifest: dict[str, dict]) -> tuple[bytes | None, str]:
    cover_id: str | None = None
    for meta in root.iter():
        if _local(meta.tag) != "meta":
            continue
        if meta.attrib.get("name") == "cover" and meta.attrib.get("content"):
            cover_id = meta.attrib["content"]
            break

    candidate: dict | None = manifest.get(cover_id or "")
    if candidate is None:
        for item in manifest.values():
            properties = item.get("properties", "").split()
            if "cover-image" in properties:
                candidate = item
                break
    if not candidate:
        return None, ".jpg"

    path = _resolve(opf_path, candidate["href"])
    try:
        raw = zf.read(path)
    except KeyError:
        return None, ".jpg"

    suffix = PurePosixPath(candidate["href"]).suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(candidate.get("media_type", "")) or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return raw, suffix


def _html_to_text(raw: bytes) -> tuple[str, str | None]:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "svg", "noscript"]):
        tag.decompose()

    heading = None
    for name in ("h1", "h2", "h3", "title"):
        node = soup.find(name)
        if node:
            heading = " ".join(node.stripped_strings).strip()
            if heading:
                break

    blocks: list[str] = []
    for node in soup.find_all(["p", "blockquote", "li", "h1", "h2", "h3", "h4"]):
        text = " ".join(node.stripped_strings)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            blocks.append(text)

    if not blocks:
        text = re.sub(r"\s+", " ", " ".join(soup.stripped_strings)).strip()
        blocks = [text] if text else []
    return "\n\n".join(blocks), heading


def _parse_nav_li(li, nav_path: str) -> TocEntry | None:
    link = li.find("a", href=True, recursive=False)
    label_node = link or li.find(["span", "p"], recursive=False)
    if label_node is None:
        # Some EPUB generators wrap the label in an extra div.
        link = li.find("a", href=True)
        label_node = link or li.find(["span", "p"])

    title = ""
    href = ""
    if label_node is not None:
        title = re.sub(r"\s+", " ", " ".join(label_node.stripped_strings)).strip()
    if link is not None:
        href = _resolve_target(nav_path, link.get("href", ""))

    children: list[TocEntry] = []
    child_ol = li.find("ol", recursive=False)
    if child_ol is not None:
        for child_li in child_ol.find_all("li", recursive=False):
            child = _parse_nav_li(child_li, nav_path)
            if child is not None:
                children.append(child)

    if not title and not children:
        return None
    if not title:
        title = "Alt bolumler"
    return TocEntry(title=title, href=href, children=children)


def _extract_epub3_toc(zf: zipfile.ZipFile, opf_path: str, manifest: dict[str, dict]) -> list[TocEntry]:
    nav_item = next(
        (item for item in manifest.values() if "nav" in item.get("properties", "").split()),
        None,
    )
    if not nav_item:
        return []

    nav_path = _resolve(opf_path, nav_item["href"])
    try:
        soup = BeautifulSoup(zf.read(nav_path), "html.parser")
    except KeyError:
        return []

    toc_nav = None
    for nav in soup.find_all("nav"):
        kind = nav.attrs.get("epub:type") or nav.attrs.get("type") or nav.attrs.get("role") or ""
        if isinstance(kind, (list, tuple)):
            kind = " ".join(str(value) for value in kind)
        if "toc" in str(kind).lower() or "doc-toc" in str(kind).lower():
            toc_nav = nav
            break
    if toc_nav is None:
        toc_nav = soup.find("nav")
    if toc_nav is None:
        return []

    root_ol = toc_nav.find("ol")
    if root_ol is None:
        return []

    entries: list[TocEntry] = []
    for li in root_ol.find_all("li", recursive=False):
        entry = _parse_nav_li(li, nav_path)
        if entry is not None:
            entries.append(entry)
    return entries


def _parse_ncx_navpoint(node: ET.Element, ncx_path: str) -> TocEntry | None:
    title = ""
    href = ""
    for child in node:
        name = _local(child.tag)
        if name == "navLabel":
            text_node = next((desc for desc in child.iter() if _local(desc.tag) == "text"), None)
            if text_node is not None and text_node.text:
                title = re.sub(r"\s+", " ", text_node.text).strip()
        elif name == "content" and child.attrib.get("src"):
            href = _resolve_target(ncx_path, child.attrib["src"])

    children: list[TocEntry] = []
    for child in node:
        if _local(child.tag) == "navPoint":
            entry = _parse_ncx_navpoint(child, ncx_path)
            if entry is not None:
                children.append(entry)
    if not title and not children:
        return None
    return TocEntry(title=title or "Alt bolumler", href=href, children=children)


def _extract_ncx_toc(zf: zipfile.ZipFile, opf_path: str, opf_root: ET.Element, manifest: dict[str, dict]) -> list[TocEntry]:
    spine_toc_id: str | None = None
    for elem in opf_root.iter():
        if _local(elem.tag) == "spine":
            spine_toc_id = elem.attrib.get("toc")
            break

    ncx_item = manifest.get(spine_toc_id or "")
    if ncx_item is None:
        ncx_item = next(
            (item for item in manifest.values() if item.get("media_type") == "application/x-dtbncx+xml"),
            None,
        )
    if not ncx_item:
        return []

    ncx_path = _resolve(opf_path, ncx_item["href"])
    try:
        root = ET.fromstring(zf.read(ncx_path))
    except (KeyError, ET.ParseError):
        return []

    nav_map = next((elem for elem in root.iter() if _local(elem.tag) == "navMap"), None)
    if nav_map is None:
        return []

    entries: list[TocEntry] = []
    for child in nav_map:
        if _local(child.tag) != "navPoint":
            continue
        entry = _parse_ncx_navpoint(child, ncx_path)
        if entry is not None:
            entries.append(entry)
    return entries


def _map_toc_to_chapters(
    entries: list[TocEntry],
    chapters: list[Chapter],
    *,
    has_navigation_toc: bool,
) -> tuple[list[TocEntry], bool]:
    chapter_by_href = {posixpath.normpath(chapter.source_href): chapter for chapter in chapters}
    represented: set[int] = set()

    def visit(entry: TocEntry) -> None:
        entry.source = "toc"
        entry.default_selected = True
        if entry.href:
            chapter = chapter_by_href.get(posixpath.normpath(_without_fragment(entry.href)))
            entry.chapter_index = chapter.index if chapter is not None else None
            if chapter is not None:
                chapter.toc_listed = True
                represented.add(chapter.index)
        for child in entry.children:
            visit(child)

    for entry in entries:
        visit(entry)

    usable_navigation_toc = has_navigation_toc and bool(represented)
    if has_navigation_toc and not usable_navigation_toc:
        # A malformed nav/NCX that maps to no parsed spine document should not
        # leave the book with an empty default selection. Treat it as no usable TOC.
        entries = []

    missing = [chapter for chapter in chapters if chapter.index not in represented]
    if missing:
        # If a usable EPUB navigation TOC exists, spine-only documents stay visible
        # to the user but are intentionally off by default. If the EPUB has no
        # usable TOC at all, keep the legacy all-spine fallback selected.
        source = "spine" if usable_navigation_toc else "spine_no_toc"
        default_selected = not usable_navigation_toc
        fallback = [
            TocEntry(
                title=chapter.title,
                href=chapter.source_href,
                chapter_index=chapter.index,
                source=source,
                default_selected=default_selected,
            )
            for chapter in missing
        ]
        if usable_navigation_toc:
            entries.append(
                TocEntry(
                    title="TOC disindaki icerik",
                    children=fallback,
                    source="spine",
                    default_selected=False,
                )
            )
        else:
            entries.extend(fallback)
    return entries, usable_navigation_toc


def parse_epub(path: str | Path) -> ParsedBook:
    epub_path = Path(path)
    if not epub_path.is_file():
        raise EpubParseError(f"EPUB bulunamadi: {epub_path}")

    try:
        zf = zipfile.ZipFile(epub_path)
    except zipfile.BadZipFile as exc:
        raise EpubParseError("Dosya gecerli bir EPUB/ZIP degil.") from exc

    with zf:
        try:
            container = ET.fromstring(zf.read(CONTAINER_PATH))
        except (KeyError, ET.ParseError) as exc:
            raise EpubParseError("EPUB container.xml okunamadi.") from exc

        rootfile = container.find(".//c:rootfile", NS_CONTAINER)
        if rootfile is None or not rootfile.attrib.get("full-path"):
            raise EpubParseError("EPUB icinde OPF rootfile bulunamadi.")
        opf_path = rootfile.attrib["full-path"]

        try:
            opf_root = ET.fromstring(zf.read(opf_path))
        except (KeyError, ET.ParseError) as exc:
            raise EpubParseError(f"OPF manifest okunamadi: {opf_path}") from exc

        title = _text(_find_metadata(opf_root, "title"), epub_path.stem)
        author = _text(_find_metadata(opf_root, "creator"), "Bilinmeyen Yazar")
        language = _text(_find_metadata(opf_root, "language"), "tr")

        manifest: dict[str, dict[str, str]] = {}
        for elem in opf_root.iter():
            if _local(elem.tag) != "item":
                continue
            item_id = elem.attrib.get("id")
            href = elem.attrib.get("href")
            if item_id and href:
                manifest[item_id] = {
                    "href": href,
                    "media_type": elem.attrib.get("media-type", ""),
                    "properties": elem.attrib.get("properties", ""),
                }

        spine_ids: list[str] = []
        for elem in opf_root.iter():
            if _local(elem.tag) == "itemref" and elem.attrib.get("idref"):
                spine_ids.append(elem.attrib["idref"])

        chapters: list[Chapter] = []
        for spine_id in spine_ids:
            item = manifest.get(spine_id)
            if not item:
                continue
            media_type = item.get("media_type", "")
            if "html" not in media_type and not item["href"].lower().endswith((".xhtml", ".html", ".htm")):
                continue
            internal_path = _resolve(opf_path, item["href"])
            try:
                raw = zf.read(internal_path)
            except KeyError:
                continue
            text, heading = _html_to_text(raw)
            if len(text.strip()) < 20:
                continue
            chapter_no = len(chapters) + 1
            chapter_title = heading or f"Bolum {chapter_no}"
            chapters.append(Chapter(chapter_no, chapter_title, text, internal_path))

        if not chapters:
            raise EpubParseError("EPUB spine icinde seslendirilebilir metin bulunamadi.")

        cover_bytes, cover_suffix = _extract_cover(zf, opf_path, opf_root, manifest)
        toc = _extract_epub3_toc(zf, opf_path, manifest)
        if not toc:
            toc = _extract_ncx_toc(zf, opf_path, opf_root, manifest)
        navigation_toc_found = bool(toc)
        toc, has_navigation_toc = _map_toc_to_chapters(
            toc,
            chapters,
            has_navigation_toc=navigation_toc_found,
        )
        metadata = BookMetadata(
            title=title,
            author=author,
            language=language,
            cover_bytes=cover_bytes,
            cover_suffix=cover_suffix,
        )
        return ParsedBook(
            metadata=metadata,
            chapters=chapters,
            toc=toc,
            has_navigation_toc=has_navigation_toc,
        )
