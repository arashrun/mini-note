import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path


HAS_QT = importlib.util.find_spec("PySide6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QUrl
    from PySide6.QtGui import QColor, QImage, QTextDocument
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

    def test_blank_lines_also_trigger_page_overflow(self):
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.body_edit.setPlainText("上" + "\n" * 100 + "下")
        for _ in range(6):
            self.app.processEvents()
        self.assertGreater(len(self.window.book.pages), 2)
        for page in self.window.book.pages:
            widget = self.window.page_widgets.get(page.id)
            if widget:
                self.assertLessEqual(widget.body_edit.document().size().height(), widget.body_edit.viewport().height())

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

    def test_reopened_image_resource_is_available(self):
        image = QImage(16, 16, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        self.window.book.images["sample"] = bytes(payload)
        self.window.book.pages[0].body = "![image](book-image:sample)"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reopen.mbook"
            from notebook_app.storage import save_book
            save_book(path, self.window.book)
            self.window._replace_book(load_book(path), path)
            self.app.processEvents()
            page = self.window.page_widgets[self.window.book.pages[0].id]
            resource = page.body_edit.document().resource(QTextDocument.ResourceType.ImageResource, QUrl("book-image:sample"))
        self.assertIsNotNone(resource)

    def test_reopen_preserves_blank_lines_and_red_text(self):
        page = self.window.page_widgets[self.window.book.pages[0].id]
        page.body_edit.setPlainText("上\n\n\n下")
        page.body_edit.moveCursor(page.body_edit.textCursor().MoveOperation.End)
        self.window._set_text_color("#d33b32")
        page.body_edit.insertPlainText("红色")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "format.mbook"
            self.window.path = path
            self.assertTrue(self.window.save_book())
            self.window._replace_book(load_book(path), path)
            self.app.processEvents()
            restored = self.window.page_widgets[self.window.book.pages[0].id].body_edit
            self.assertEqual(restored.toPlainText(), "上\n\n\n下红色")
            cursor = restored.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.movePosition(cursor.MoveOperation.Left)
            self.assertEqual(cursor.charFormat().foreground().color().name(), "#d33b32")

    def test_typed_link_becomes_blue_anchor(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        page = self.window.page_widgets[self.window.book.pages[0].id]
        page.body_edit.setFocus()
        QTest.keyClicks(page.body_edit, "[OpenAI](https://openai.com)")
        self.assertEqual(page.body_edit.toPlainText(), "OpenAI")
        cursor = page.body_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Left)
        self.assertEqual(cursor.charFormat().anchorHref(), "https://openai.com")
        page.body_edit.setFocus()
        QTest.keyClick(page.body_edit, Qt.Key.Key_Escape)

    def test_heading_syntax_stays_plain_and_red_mode_applies_to_new_text(self):
        from PySide6.QtTest import QTest
        page = self.window.page_widgets[self.window.book.pages[0].id]
        page.body_edit.setFocus()
        QTest.keyClicks(page.body_edit, "# plain")
        self.assertEqual(page.body_edit.toPlainText(), "# plain")
        self.window._set_text_color("#d33b32")
        QTest.keyClicks(page.body_edit, " red")
        self.assertEqual(page.body_edit.currentCharFormat().foreground().color().name(), "#d33b32")

    def test_color_shortcuts_and_escape_clear_one_active_layer(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier)
        QTest.keyClick(editor, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(editor, Qt.Key.Key_I, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#246fb5")
        self.assertEqual(self.window.format_label.text(), "蓝色 · 粗体 · 斜体")

        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#26322f")
        self.assertTrue(editor.fontItalic())
        self.assertGreater(editor.fontWeight(), 400)
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertEqual(editor.fontWeight(), 400)
        self.assertTrue(editor.fontItalic())
        QTest.keyClick(editor, Qt.Key.Key_Escape)
        self.assertFalse(editor.fontItalic())
        self.assertEqual(self.window.format_label.text(), "默认样式")

    def test_alt_zero_returns_to_default_color(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#d33b32")
        QTest.keyClick(editor, Qt.Key.Key_0, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#26322f")

    def test_pagination_keeps_active_color_and_weight(self):
        from PySide6.QtGui import QTextCursor
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setFocus()
        editor.setPlainText("\n".join("正文段落" for _ in range(80)))
        editor.moveCursor(QTextCursor.MoveOperation.End)
        self.window._set_text_color("#d33b32")
        self.window._format_char("bold")
        for _ in range(12):
            self.app.processEvents()
        continued = self.window._active_editor()
        self.assertIs(self.window.focusWidget(), continued)
        self.assertEqual(continued.currentCharFormat().foreground().color().name(), "#d33b32")
        self.assertGreater(continued.fontWeight(), 400)

    def test_escape_does_not_recolor_selected_text(self):
        from PySide6.QtGui import QTextCursor
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setPlainText("hello world")
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(5, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        self.window._set_text_color("#246fb5")
        self.window._deactivate_style(editor)
        cursor = editor.textCursor()
        cursor.setPosition(2)
        self.assertEqual(cursor.charFormat().foreground().color().name(), "#246fb5")
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#26322f")


if __name__ == "__main__":
    unittest.main()
