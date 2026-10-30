from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

from PySide6.QtCore import QPropertyAnimation, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextDocument, QTextListFormat
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QToolBar, QVBoxLayout, QWidget,
)

from notebook_app.model import Book, Page, Typography
from notebook_app.page import PageWidget
from notebook_app.storage import MAX_IMAGE_BYTES, load_book, save_book
from notebook_app.typography_dialog import TypographyDialog


DEFAULT_INK = "#26322f"
TEXT_COLORS = (
    ("默认", None),
    ("红色", "#d33b32"),
    ("橙色", "#bd5a27"),
    ("金色", "#92700a"),
    ("绿色", "#288052"),
    ("蓝色", "#246fb5"),
    ("紫色", "#7953a6"),
    ("灰色", "#687078"),
)


class ImagePreviewDialog(QDialog):
    def __init__(self, image: QImage, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(parent.size() if parent else image.size())
        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background: #fffdf7; border: 1px solid #d5d8ce;")
        self.image_label.setPixmap(QPixmap.fromImage(image))
        self.image_label.adjustSize()
        self._image = image

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        available = self.size()
        pixmap = QPixmap.fromImage(self._image).scaled(
            max(1, available.width() - 80), max(1, available.height() - 80),
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(pixmap)
        self.image_label.setGeometry(
            (self.width() - pixmap.width()) // 2 - 40,
            (self.height() - pixmap.height()) // 2 - 40,
            pixmap.width() + 80, pixmap.height() + 80,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 130))

    def mousePressEvent(self, event) -> None:
        if not self.image_label.geometry().contains(event.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Space):
            self.close()
            return
        super().keyPressEvent(event)


class NotebookWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.book = Book()
        self.path: Path | None = None
        self.dirty = False
        self.spread_start = 0
        self.page_widgets: dict[str, PageWidget] = {}
        self._last_active_page_id: str | None = None
        self._building = False
        self.resize(1360, 850)
        self.setMinimumSize(870, 580)
        self._build_ui()
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self._show_spread()
        self._update_title()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QSplitter, #bookArea { background: #23342f; }
            #sidebar { background: #192a27; color: #e7eee8; }
            #sidebar QLabel { color: #bed2c5; font-size: 12px; font-weight: 700; }
            QListWidget { background: transparent; color: #e7eee8; border: 0; outline: 0; font-size: 13px; }
            QListWidget::item { padding: 8px 10px; }
            QListWidget::item:selected { background: #365d55; }
            QToolBar { background: #f0f2ed; border: 0; padding: 5px; spacing: 4px; }
            QToolButton { color: #23342f; padding: 6px 8px; }
            QToolButton:hover { background: #dbe5de; }
            QComboBox { min-width: 90px; padding: 4px; }
            #paperPage { border: 1px solid #e2e0d5; }
            #pageTitle { background: transparent; border: 0; border-bottom: 1px solid #c9cec4;
                         color: #253c35; font-size: 20px; font-weight: 600; padding: 3px 0 8px; }
            #pageBody { background: transparent; border: 0; color: #26322f; }
            #statusStrip { background: #192a27; color: #e0e9e2; }
        """)
        self._install_actions()

        splitter = QSplitter()
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(170)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(17, 22, 12, 12)
        side_layout.addWidget(QLabel("目录"))
        self.chapters = QListWidget()
        self.chapters.itemClicked.connect(self._jump_to_chapter)
        side_layout.addWidget(self.chapters)
        splitter.addWidget(sidebar)

        book_area = QWidget()
        book_area.setObjectName("bookArea")
        book_layout = QVBoxLayout(book_area)
        book_layout.setContentsMargins(28, 24, 28, 14)
        self.spread = QWidget()
        self.spread_layout = QHBoxLayout(self.spread)
        self.spread_layout.setContentsMargins(0, 0, 0, 0)
        self.spread_layout.setSpacing(0)
        book_layout.addWidget(self.spread, 1)
        nav = QFrame()
        nav.setObjectName("statusStrip")
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(12, 8, 12, 8)
        previous = self._action(None, "上一页", "Alt+Left", self.previous_spread)
        following = self._action(None, "下一页", "Alt+Right", self.next_spread)
        for label, action in (("‹  上一页", previous), ("下一页  ›", following)):
            button = QPushButton(label)
            button.clicked.connect(action.trigger)
            button.setStyleSheet("background: transparent; color: #e0e9e2; border: 0; padding: 4px 12px;")
            nav_layout.addWidget(button)
            if action is previous:
                nav_layout.addStretch()
        self.position_label = QLabel()
        self.position_label.setStyleSheet("color: #e0e9e2;")
        nav_layout.insertWidget(2, self.position_label)
        nav_layout.insertStretch(3)
        self.format_label = QLabel()
        self.format_label.setFixedWidth(170)
        self.format_label.setStyleSheet("color: #bed2c5;")
        nav_layout.insertWidget(1, self.format_label)
        book_layout.addWidget(nav)
        splitter.addWidget(book_area)
        splitter.setSizes([210, 1150])
        self.setCentralWidget(splitter)

    def _install_actions(self) -> None:
        self.actions_by_name = {}
        definitions = (
            ("new", "新建", "Ctrl+N", self.new_book), ("open", "打开", "Ctrl+O", self.open_book),
            ("save", "保存", "Ctrl+S", self.save_book), ("save_as", "另存为", "Ctrl+Shift+S", self.save_book_as),
            ("bold", "粗体", "Ctrl+B", lambda: self._format_char("bold")),
            ("italic", "斜体", "Ctrl+I", lambda: self._format_char("italic")),
            ("list", "列表", "Ctrl+Shift+L", self._format_list),
            ("link", "链接", "Ctrl+K", self._insert_link), ("image", "插图", "Ctrl+Shift+I", self.insert_image),
            ("insert_page", "插入页面", "Ctrl+Shift+N", self.insert_page), ("remove_page", "撕掉页面", "Ctrl+Shift+D", self.remove_page),
            ("toggle_toc", "显示/隐藏目录", "Ctrl+Shift+O", self.toggle_toc),
            ("shortcuts", "快捷键说明", "F1", self.show_shortcuts),
        )
        for key, label, shortcut, callback in definitions:
            self.actions_by_name[key] = self._action(None, label, shortcut, callback)
        for number, (label, color) in enumerate(TEXT_COLORS):
            action = self._action(
                None, f"文字颜色：{label}", f"Alt+{number}",
                lambda checked=False, value=color: self._set_text_color(value),
            )
            swatch = QPixmap(14, 14)
            swatch.fill(QColor(color or DEFAULT_INK))
            action.setIcon(QIcon(swatch))
            self.actions_by_name[f"color_{number}"] = action
        self.paper_combo = QComboBox()
        for label, value in (("空白", "plain"), ("横线", "ruled"), ("方格", "grid")):
            self.paper_combo.addItem(label, value)
        self.paper_combo.setCurrentIndex(1)
        self.paper_combo.currentIndexChanged.connect(self._change_paper)

    def contextMenuEvent(self, event) -> None:
        self._show_context_menu(event.globalPos())

    def _show_context_menu(self, global_pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        file_menu = menu.addMenu("文件")
        for key in ("new", "open", "save", "save_as"):
            file_menu.addAction(self.actions_by_name[key])
        edit_menu = menu.addMenu("编辑")
        for key in ("bold", "italic", "list", "link", "image"):
            edit_menu.addAction(self.actions_by_name[key])
        colors_menu = edit_menu.addMenu("文字颜色")
        for number in range(len(TEXT_COLORS)):
            colors_menu.addAction(self.actions_by_name[f"color_{number}"])
        page_menu = menu.addMenu("页面")
        page_menu.addAction(self.actions_by_name["insert_page"])
        page_menu.addAction(self.actions_by_name["remove_page"])
        paper_menu = menu.addMenu("纸张")
        for index in range(self.paper_combo.count()):
            action = paper_menu.addAction(self.paper_combo.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.paper_combo.currentIndex())
            action.triggered.connect(lambda checked=False, i=index: self.paper_combo.setCurrentIndex(i))
        menu.addAction("正文排版...", self.open_typography_dialog)
        menu.addSeparator()
        menu.addAction(self.actions_by_name["toggle_toc"])
        menu.addAction(self.actions_by_name["shortcuts"])
        menu.exec(global_pos)

    def toggle_toc(self) -> None:
        sidebar = self.chapters.parentWidget()
        while sidebar and sidebar.objectName() != "sidebar":
            sidebar = sidebar.parentWidget()
        if sidebar:
            sidebar.setVisible(not sidebar.isVisible())

    def show_shortcuts(self) -> None:
        text = "\n".join(f"{action.text()}\t{action.shortcut().toString()}" for action in self.actions_by_name.values())
        QMessageBox.information(self, "快捷键说明", text)

    def _action(self, toolbar: QToolBar | None, label: str, shortcut: str, callback) -> QAction:
        action = QAction(label, self)
        action.setShortcut(shortcut)
        action.triggered.connect(callback)
        self.addAction(action)
        if toolbar is not None:
            toolbar.addAction(action)
        return action

    def _page_widget(self, page: Page, number: int) -> PageWidget:
        if page.id not in self.page_widgets:
            widget = PageWidget(page, number, self.book.paper_style, self.book.images, self.book.typography)
            widget.changed.connect(self._page_changed)
            widget.contextMenuRequested.connect(self._show_context_menu)
            widget.body_edit.imagePasted.connect(lambda image, data, editor=widget.body_edit: self._insert_image_data(editor, image, data))
            widget.body_edit.imageDoubleClicked.connect(self._show_image_fullscreen)
            widget.body_edit.deactivateStyleRequested.connect(lambda editor=widget.body_edit: self._deactivate_style(editor))
            widget.body_edit.currentCharFormatChanged.connect(lambda fmt, editor=widget.body_edit: self._update_format_label(editor))
            self.page_widgets[page.id] = widget
        widget = self.page_widgets[page.id]
        widget.set_number(number)
        return widget

    def _show_spread(self, animate: bool = False) -> None:
        while self.spread_layout.count():
            item = self.spread_layout.takeAt(0)
            if item.widget():
                widget = item.widget()
                widget.setParent(None)
                if widget not in self.page_widgets.values():
                    widget.deleteLater()
        for offset in (0, 1):
            if offset:
                spine = QFrame()
                spine.setFixedWidth(16)
                spine.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #92958c, stop:0.5 #d2d1c8, stop:1 #858a80);")
                self.spread_layout.addWidget(spine)
            index = self.spread_start + offset
            if index < len(self.book.pages):
                self.spread_layout.addWidget(self._page_widget(self.book.pages[index], index + 1), 1)
            else:
                blank = QFrame()
                blank.setStyleSheet("background: #fffdf7; border: 1px solid #e2e0d5;")
                self.spread_layout.addWidget(blank, 1)
        self.position_label.setText(f"{self.spread_start + 1}–{min(self.spread_start + 2, len(self.book.pages))} / {len(self.book.pages)}")
        self._refresh_chapters()
        self._update_format_label(self._active_editor())
        if animate:
            effect = QGraphicsOpacityEffect(self.spread)
            self.spread.setGraphicsEffect(effect)
            self._animation = QPropertyAnimation(effect, b"opacity", self)
            self._animation.setDuration(180)
            self._animation.setStartValue(0.55)
            self._animation.setEndValue(1.0)
            self._animation.finished.connect(lambda: self.spread.setGraphicsEffect(None))
            self._animation.start()

    def _refresh_chapters(self) -> None:
        self.chapters.clear()
        for index, title in self.book.chapters():
            item = QListWidgetItem(f"{index + 1:02d}  {title}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.chapters.addItem(item)

    def _jump_to_chapter(self, item) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        self.spread_start = index - index % 2
        self._show_spread(True)

    def _page_changed(self) -> None:
        if self._building:
            return
        self.dirty = True
        self._update_title()
        self._refresh_chapters()

    def _active_index(self) -> int:
        focus = self.focusWidget()
        for index, page in enumerate(self.book.pages):
            widget = self.page_widgets.get(page.id)
            if widget and focus and self.spread_start <= index < self.spread_start + 2 and (
                focus is widget.title_edit or focus is widget.body_edit or widget.body_edit.isAncestorOf(focus)
            ):
                return index
        if self._last_active_page_id:
            for index, page in enumerate(self.book.pages):
                if page.id == self._last_active_page_id and self.spread_start <= index < self.spread_start + 2:
                    return index
        return self.spread_start

    def _focus_changed(self, old, current) -> None:
        if current is None:
            return
        for page in self.book.pages:
            widget = self.page_widgets.get(page.id)
            if widget and (current is widget.title_edit or current is widget.body_edit or widget.body_edit.isAncestorOf(current)):
                self._last_active_page_id = page.id
                self._update_format_label(widget.body_edit)
                return

    def _active_editor(self):
        index = self._active_index()
        return self._page_widget(self.book.pages[index], index + 1).body_edit

    def _format_char(self, kind: str) -> None:
        editor = self._active_editor()
        fmt = QTextCharFormat()
        if kind == "bold":
            fmt.setFontWeight(QFont.Weight.Normal if editor.fontWeight() == QFont.Weight.Bold else QFont.Weight.Bold)
        else:
            fmt.setFontItalic(not editor.fontItalic())
        editor.mergeCurrentCharFormat(fmt)
        editor.setFocus()
        self._update_format_label(editor)

    def _set_text_color(self, color: str | None) -> None:
        editor = self._active_editor()
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color or DEFAULT_INK))
        editor.mergeCurrentCharFormat(fmt)
        editor.setFocus()
        self._update_format_label(editor)

    def _deactivate_style(self, editor) -> None:
        cursor = editor.textCursor()
        if cursor.hasSelection():
            cursor.clearSelection()
            editor.setTextCursor(cursor)
        current = editor.currentCharFormat()
        color = current.foreground().color()
        fmt = QTextCharFormat()
        if color.isValid() and color.name().lower() not in (DEFAULT_INK, "#000000"):
            fmt.setForeground(QColor(DEFAULT_INK))
        elif current.fontWeight() > QFont.Weight.Normal:
            fmt.setFontWeight(QFont.Weight.Normal)
        elif current.fontItalic():
            fmt.setFontItalic(False)
        else:
            return
        editor.mergeCurrentCharFormat(fmt)
        self._update_format_label(editor)

    def _update_format_label(self, editor) -> None:
        if not hasattr(self, "format_label"):
            return
        current = editor.currentCharFormat()
        color = current.foreground().color()
        active = []
        if color.isValid() and color.name().lower() not in (DEFAULT_INK, "#000000"):
            active.append(next((name for name, value in TEXT_COLORS if value == color.name().lower()), "自定义颜色"))
        if current.fontWeight() > QFont.Weight.Normal:
            active.append("粗体")
        if current.fontItalic():
            active.append("斜体")
        self.format_label.setText(" · ".join(active) if active else "默认样式")

    def _format_list(self) -> None:
        editor = self._active_editor()
        editor.textCursor().createList(QTextListFormat.Style.ListDisc)
        editor.setFocus()

    def _insert_link(self) -> None:
        editor = self._active_editor()
        cursor = editor.textCursor()
        url, accepted = QInputDialog.getText(self, "插入链接", "地址")
        if not accepted or not url.strip():
            return
        if not cursor.hasSelection():
            label, accepted = QInputDialog.getText(self, "插入链接", "显示文字")
            if not accepted or not label:
                return
            cursor.insertText(label)
            cursor.setPosition(cursor.position() - len(label), QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url.strip())
        cursor.mergeCharFormat(fmt)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def _change_paper(self) -> None:
        style = self.paper_combo.currentData()
        if not style or style == self.book.paper_style:
            return
        self.book.paper_style = style
        for widget in self.page_widgets.values():
            widget.set_paper_style(style)
        self.dirty = True
        self._update_title()

    def open_typography_dialog(self) -> None:
        dialog = TypographyDialog(self.book.typography, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_typography(dialog.selected_typography())

    def apply_typography(self, typography: Typography) -> None:
        if typography == self.book.typography:
            return
        self._building = True
        try:
            self.book.typography = typography
            for widget in self.page_widgets.values():
                widget.apply_typography(typography)
        finally:
            self._building = False
        self.dirty = True
        self._update_title()

    def previous_spread(self) -> None:
        if self.spread_start >= 2:
            self.spread_start -= 2
            self._show_spread(True)

    def next_spread(self) -> None:
        if self.spread_start + 2 < len(self.book.pages):
            self.spread_start += 2
            self._show_spread(True)

    def insert_page(self) -> None:
        index = self._active_index()
        self.book.insert_page(index)
        self.dirty = True
        self.spread_start = (index + 1) // 2 * 2
        self._update_title()
        self._show_spread(True)

    def remove_page(self) -> None:
        index = self._active_index()
        page = self.book.pages[index]
        if page.title or page.body.strip():
            answer = QMessageBox.question(self, "撕掉这一页", "这页的标题和正文将被删除。确定撕掉吗？")
            if answer != QMessageBox.StandardButton.Yes:
                return
        widget = self.page_widgets.pop(page.id, None)
        if widget:
            widget.setParent(None)
            widget.deleteLater()
        self.book.remove_page(index)
        self.spread_start = min(self.spread_start, (len(self.book.pages) - 1) // 2 * 2)
        self.dirty = True
        self._update_title()
        self._show_spread(True)

    def insert_image(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "插入图片", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not filename:
            return
        data = Path(filename).read_bytes()
        image = QImage.fromData(data)
        if len(data) > MAX_IMAGE_BYTES or image.isNull() or image.width() == 0:
            QMessageBox.warning(self, "无法插入", "图片无效或大于 30 MB。")
            return
        index = self._active_index()
        editor = self._page_widget(self.book.pages[index], index + 1).body_edit
        self._insert_image_data(editor, image, data)

    def _insert_image_data(self, editor, image: QImage, data: bytes) -> None:
        if len(data) > MAX_IMAGE_BYTES or image.isNull() or image.width() == 0:
            QMessageBox.warning(self, "无法插入", "图片无效或大于 30 MB。")
            return
        name = uuid4().hex
        self.book.images[name] = data
        for widget in self.page_widgets.values():
            widget.body_edit.document().addResource(
                QTextDocument.ResourceType.ImageResource, QUrl(f"book-image:{name}"), image
            )
        page_widget = next((widget for widget in self.page_widgets.values() if widget.body_edit is editor), None)
        if page_widget is None:
            page_widget = self._page_widget(self.book.pages[self._active_index()], self._active_index() + 1)
        page_widget.insert_image(name, image)
        self.dirty = True
        self._update_title()

    def _show_image_fullscreen(self, name: str) -> None:
        data = self.book.images.get(name)
        image = QImage.fromData(data) if data else QImage()
        if image.isNull():
            return
        dialog = ImagePreviewDialog(image, self)
        dialog.exec()

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "未保存的修改", "保存当前文档的修改吗？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_book()
        return True

    def new_book(self) -> None:
        if self._maybe_save():
            self._replace_book(Book(), None)

    def open_book(self) -> None:
        if not self._maybe_save():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "打开文档", "", "Paperbound (*.mbook)")
        if filename:
            try:
                self._replace_book(load_book(filename), Path(filename))
            except (OSError, ValueError, KeyError, UnicodeError, BadZipFile) as error:
                QMessageBox.critical(self, "无法打开", str(error))

    def save_book_as(self) -> bool:
        previous = self.path
        self.path = None
        if self.save_book():
            return True
        self.path = previous
        self._update_title()
        return False

    def save_book(self) -> bool:
        if self.path is None:
            filename, _ = QFileDialog.getSaveFileName(self, "保存文档", "", "Paperbound (*.mbook)")
            if not filename:
                return False
            self.path = Path(filename).with_suffix(".mbook")
        try:
            save_book(self.path, self.book)
        except OSError as error:
            QMessageBox.critical(self, "无法保存", str(error))
            return False
        self.dirty = False
        self._update_title()
        return True

    def _replace_book(self, book: Book, path: Path | None) -> None:
        self._building = True
        for widget in self.page_widgets.values():
            widget.setParent(None)
            widget.deleteLater()
        self.page_widgets.clear()
        self._last_active_page_id = None
        self.book = book
        self.path = path
        self.dirty = False
        self.spread_start = 0
        self.paper_combo.setCurrentIndex(("plain", "ruled", "grid").index(book.paper_style))
        self._show_spread()
        self._update_title()
        self._building = False

    def _update_title(self) -> None:
        name = self.path.stem if self.path else "未命名"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - Paperbound")

    def closeEvent(self, event) -> None:
        if self._maybe_save():
            event.accept()
        else:
            event.ignore()
