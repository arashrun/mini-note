"""Read and write the single-file book container."""

import json
import os
import tempfile
import zipfile
from pathlib import Path

from notebook_app.model import Book, PAPER_STYLES, Page


FORMAT_VERSION = 1
MAX_IMAGE_BYTES = 30 * 1024 * 1024


def load_book(path: str | Path) -> Book:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("pages"), list):
            raise ValueError("Invalid book manifest")
        if manifest.get("version") != FORMAT_VERSION:
            raise ValueError("Unsupported book version")
        style = manifest.get("paper_style", "ruled")
        if style not in PAPER_STYLES:
            raise ValueError("Invalid paper style")
        pages = []
        seen_pages = set()
        for entry in manifest["pages"]:
            if not isinstance(entry, dict):
                raise ValueError("Invalid page entry")
            page_id = entry["id"]
            if not isinstance(page_id, str) or not page_id.isascii() or not page_id.isalnum() or page_id in seen_pages:
                raise ValueError("Invalid page ID")
            seen_pages.add(page_id)
            body = archive.read(f"pages/{page_id}.md").decode("utf-8")
            html_name = f"pages/{page_id}.html"
            html = archive.read(html_name).decode("utf-8") if html_name in archive.namelist() else ""
            pages.append(Page(page_id, str(entry.get("title", "")), body, bool(entry.get("manual", True)), html))
        images = {}
        image_names = manifest.get("images", [])
        if not isinstance(image_names, list):
            raise ValueError("Invalid image list")
        for name in image_names:
            if not isinstance(name, str) or not name.isascii() or not name.isalnum() or name in images:
                raise ValueError("Invalid image ID")
            info = archive.getinfo(f"images/{name}")
            if info.file_size > MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds size limit")
            images[name] = archive.read(info)
    return Book(pages, style, images)


def save_book(path: str | Path, book: Book) -> None:
    path = Path(path)
    manifest = {
        "version": FORMAT_VERSION,
        "paper_style": book.paper_style,
        "pages": [
            {"id": page.id, "title": page.title, "manual": page.manual}
            for page in book.pages
        ],
        "images": list(book.images),
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for page in book.pages:
                archive.writestr(f"pages/{page.id}.md", page.body)
                archive.writestr(f"pages/{page.id}.html", page.html)
            for name, data in book.images.items():
                archive.writestr(f"images/{name}", data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
