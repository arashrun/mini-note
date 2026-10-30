import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path


HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QApplication

    from notebook_app.storage import load_book
    from notebook_app.window import NotebookWindow


@unittest.skipUnless(HAS_QT, "PySide6 is not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = NotebookWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.app.processEvents()

    def test_title_appears_in_chapter_list_and_saves(self):
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.title_edit.setText("序章")
        first.body_edit.setPlainText("第一段")
        self.app.processEvents()
        self.assertEqual(self.window.chapters.count(), 1)
        with tempfile.TemporaryDirectory() as directory:
            self.window.path = Path(directory) / "test.mbook"
            self.assertTrue(self.window.save_book())
            restored = load_book(self.window.path)
        self.assertEqual(restored.pages[0].title, "序章")
        self.assertIn("第一段", restored.pages[0].body)

    def test_overflow_creates_following_page(self):
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.body_edit.setPlainText("\n".join(f"第 {i} 段正文" for i in range(80)))
        for _ in range(5):
            self.app.processEvents()
        self.assertGreater(len(self.window.book.pages), 2)
        self.assertFalse(self.window.book.pages[1].manual)
        for page in self.window.book.pages[:2]:
            editor = self.window.page_widgets[page.id].body_edit
            self.assertLessEqual(editor.document().size().height(), editor.viewport().height())
        body = "".join(page.body for page in self.window.book.pages)
        numbers = [int(value) for value in re.findall(r"第 ([0-9]+) 段正文", body)]
        self.assertEqual(sorted(numbers), list(range(80)))

    def test_inserted_image_is_embedded_in_book(self):
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self.assertTrue(image.save(buffer, "PNG"))
        buffer.close()
        self.window.book.images["sample"] = bytes(payload)
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.insert_image("sample", image)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "images.mbook"
            self.window.path = path
            self.assertTrue(self.window.save_book())
            restored = load_book(path)
        self.assertIn("sample", restored.images)
        self.assertIn("book-image:sample", restored.pages[0].body)


if __name__ == "__main__":
    unittest.main()
