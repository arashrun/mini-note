import tempfile
import unittest
import zipfile
from pathlib import Path

from notebook_app.model import Book, Page, Typography
from notebook_app.storage import load_book, save_book


class StorageTests(unittest.TestCase):
    def test_round_trip_pages_and_images(self):
        book = Book([Page(title="第一章", body="**正文**")], "grid", {"cover": b"image"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.mbook"
            save_book(path, book)
            restored = load_book(path)
        self.assertEqual(restored.paper_style, "grid")
        self.assertEqual(restored.pages[0].title, "第一章")
        self.assertEqual(restored.pages[0].body, "**正文**")
        self.assertEqual(restored.images["cover"], b"image")

    def test_remove_last_page_keeps_blank_page(self):
        book = Book()
        book.remove_page(0)
        self.assertEqual(len(book.pages), 2)

    def test_manual_insert_retains_editable_spread(self):
        book = Book()
        inserted = book.insert_page(0)
        self.assertTrue(inserted.manual)
        self.assertEqual(len(book.pages) % 2, 0)

    def test_save_replaces_existing_book(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.mbook"
            save_book(path, Book())
            updated = Book()
            updated.pages[0].title = "更新"
            save_book(path, updated)
            self.assertEqual(load_book(path).pages[0].title, "更新")

    def test_rejects_invalid_manifest_without_extracting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.mbook"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", '{"version":1,"pages":[{"id":"../bad"}]}')
            with self.assertRaises(ValueError):
                load_book(path)

    def test_typography_round_trip(self):
        book = Book(typography=Typography("Noto Serif SC", 15, 145))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.mbook"
            save_book(path, book)
            restored = load_book(path)
        self.assertEqual(restored.typography, book.typography)

    def test_legacy_book_uses_default_typography(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.mbook"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("manifest.json", '{"version":1,"pages":[{"id":"a"}]}')
                archive.writestr("pages/a.md", "Old text")
            restored = load_book(path)
        self.assertEqual(restored.typography, Typography())


if __name__ == "__main__":
    unittest.main()
