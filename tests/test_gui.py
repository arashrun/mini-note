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
    from notebook_app.model import Typography
    from notebook_app.typography_dialog import TypographyDialog
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

    def test_long_text_stays_on_page_and_scrolls(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.body_edit.setPlainText("\n".join(f"第 {i} 段正文" for i in range(80)))
        self.app.processEvents()
        self.assertEqual(len(self.window.book.pages), 2)
        self.assertGreater(first.body_edit.verticalScrollBar().maximum(), 0)
        self.assertFalse(first.body_edit.verticalScrollBar().isVisible())
        first.body_edit.verticalScrollBar().setValue(0)
        wheel = QWheelEvent(
            QPointF(10, 10), QPointF(first.body_edit.viewport().mapToGlobal(QPoint(10, 10))),
            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False,
        )
        self.app.sendEvent(first.body_edit.viewport(), wheel)
        self.assertGreater(first.body_edit.verticalScrollBar().value(), 0)
        first.body_edit.verticalScrollBar().setValue(first.body_edit.verticalScrollBar().maximum())
        self.assertGreater(first.body_edit.verticalScrollBar().value(), 0)
        second = self.window.page_widgets[self.window.book.pages[1].id].body_edit
        self.assertEqual(second.verticalScrollBar().value(), 0)
        numbers = [int(value) for value in re.findall(r"第 ([0-9]+) 段正文", self.window.book.pages[0].body)]
        self.assertEqual(sorted(numbers), list(range(80)))
        self.assertEqual(self.window.book.pages[1].body.strip(), "")

    def test_blank_lines_scroll_without_creating_page(self):
        first = self.window.page_widgets[self.window.book.pages[0].id]
        first.body_edit.setPlainText("上" + "\n" * 100 + "下")
        self.app.processEvents()
        self.assertEqual(len(self.window.book.pages), 2)
        self.assertGreater(first.body_edit.verticalScrollBar().maximum(), 0)
        self.assertTrue(first.body_edit.toPlainText().endswith("下"))

    def test_scroll_position_survives_spread_navigation(self):
        first = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        first.setPlainText("\n".join("正文" for _ in range(80)))
        self.app.processEvents()
        first.verticalScrollBar().setValue(first.verticalScrollBar().maximum())
        position = first.verticalScrollBar().value()
        self.window.book.insert_page(1)
        self.window.next_spread()
        self.window.previous_spread()
        self.app.processEvents()
        self.assertEqual(first.verticalScrollBar().value(), position)

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

    def test_scrolling_keeps_active_color_and_weight(self):
        from PySide6.QtGui import QTextCursor
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setFocus()
        editor.setPlainText("\n".join("正文段落" for _ in range(80)))
        editor.moveCursor(QTextCursor.MoveOperation.End)
        self.window._set_text_color("#d33b32")
        self.window._format_char("bold")
        self.app.processEvents()
        self.assertEqual(len(self.window.book.pages), 2)
        self.assertIs(self.window.focusWidget(), editor)
        self.assertEqual(editor.currentCharFormat().foreground().color().name(), "#d33b32")
        self.assertGreater(editor.fontWeight(), 400)

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

    def test_typography_changes_layout_and_clears_old_undo(self):
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.insertPlainText("第一段\n第二段")
        self.assertTrue(editor.document().isUndoAvailable())
        old_height = editor.document().size().height()
        settings = Typography("", 17, 160)
        self.window.apply_typography(settings)
        self.app.processEvents()
        self.assertEqual(self.window.book.typography, settings)
        self.assertFalse(editor.document().isUndoAvailable())
        self.assertGreater(editor.document().size().height(), old_height)
        self.assertEqual(editor.textCursor().blockFormat().lineHeight(), 160)

        editor.insertPlainText("后续")
        self.assertTrue(editor.document().isUndoAvailable())
        editor.undo()
        self.assertEqual(editor.textCursor().blockFormat().lineHeight(), 160)

    def test_typography_round_trip(self):
        settings = Typography("", 15, 145)
        self.window.apply_typography(settings)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.mbook"
            self.window.path = path
            self.assertTrue(self.window.save_book())
            self.window._replace_book(load_book(path), path)
            self.app.processEvents()
            self.assertEqual(self.window.book.typography, settings)
            editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
            self.assertEqual(editor.textCursor().blockFormat().lineHeight(), 145)

    def test_typography_preserves_inline_color_and_weight(self):
        from PySide6.QtGui import QTextCursor
        editor = self.window.page_widgets[self.window.book.pages[0].id].body_edit
        editor.setPlainText("第一段")
        editor.setFocus()
        cursor = editor.textCursor()
        cursor.setPosition(0)
        cursor.setPosition(3, QTextCursor.MoveMode.KeepAnchor)
        editor.setTextCursor(cursor)
        self.window._set_text_color("#246fb5")
        self.window._format_char("bold")
        self.window.apply_typography(Typography("", 17, 150))
        cursor = editor.textCursor()
        cursor.setPosition(1)
        self.assertEqual(cursor.charFormat().foreground().color().name(), "#246fb5")
        self.assertGreater(cursor.charFormat().fontWeight(), 400)
        self.assertEqual(cursor.charFormat().fontPointSize(), 17)

    def test_typography_dialog_collects_settings(self):
        dialog = TypographyDialog(Typography(), self.window)
        dialog.font_size.setValue(16)
        dialog.line_spacing.setValue(150)
        self.assertEqual(dialog.selected_typography(), Typography("", 16, 150))


if __name__ == "__main__":
    unittest.main()
