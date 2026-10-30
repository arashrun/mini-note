from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QFont, QImage, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextDocumentFragment, QTextListFormat
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QToolBar, QVBoxLayout, QWidget,
)

from notebook_app.model import Book, Page
from notebook_app.page import PageWidget
from notebook_app.storage import MAX_IMAGE_BYTES, load_book, save_book


class NotebookWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.book = Book()
        self.path: Path | None = None
        self.dirty = False
        self.spread_start = 0
        self.page_widgets: dict[str, PageWidget] = {}
        self._last_active_page_id: str | None = None
        self._reflow_pending = False
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
            #pageBody { background: transparent; border: 0; color: #26322f;
                        font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; font-size: 15px; }
            #statusStrip { background: #192a27; color: #e0e9e2; }
        """)
        toolbar = QToolBar("编辑")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        for label, shortcut, callback in (
            ("新建", "Ctrl+N", self.new_book), ("打开", "Ctrl+O", self.open_book),
            ("保存", "Ctrl+S", self.save_book),
            ("另存为", "Ctrl+Shift+S", self.save_book_as),
        ):
            self._action(toolbar, label, shortcut, callback)
        toolbar.addSeparator()
        for label, shortcut, callback in (
            ("B", "Ctrl+B", lambda: self._format_char("bold")),
            ("I", "Ctrl+I", lambda: self._format_char("italic")),
            ("标题", "Ctrl+1", self._format_heading),
            ("列表", "Ctrl+Shift+L", self._format_list),
            ("链接", "Ctrl+K", self._insert_link),
            ("插图", "Ctrl+Shift+I", self.insert_image),
        ):
            self._action(toolbar, label, shortcut, callback)
        toolbar.addSeparator()
        self._action(toolbar, "插页", "Ctrl+Shift+N", self.insert_page)
        self._action(toolbar, "撕页", "Ctrl+Shift+D", self.remove_page)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("  纸张  "))
        self.paper_combo = QComboBox()
        for label, value in (("空白", "plain"), ("横线", "ruled"), ("方格", "grid")):
            self.paper_combo.addItem(label, value)
        self.paper_combo.setCurrentIndex(1)
        self.paper_combo.currentIndexChanged.connect(self._change_paper)
        toolbar.addWidget(self.paper_combo)

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
        book_layout.addWidget(nav)
        splitter.addWidget(book_area)
        splitter.setSizes([210, 1150])
        self.setCentralWidget(splitter)

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
            widget = PageWidget(page, number, self.book.paper_style, self.book.images)
            widget.changed.connect(self._page_changed)
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
        if animate:
            effect = QGraphicsOpacityEffect(self.spread)
            self.spread.setGraphicsEffect(effect)
            self._animation = QPropertyAnimation(effect, b"opacity", self)
            self._animation.setDuration(180)
            self._animation.setStartValue(0.55)
            self._animation.setEndValue(1.0)
            self._animation.finished.connect(lambda: self.spread.setGraphicsEffect(None))
            self._animation.start()
        if not self._building:
            self._schedule_reflow()

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
        self._schedule_reflow()

    def _schedule_reflow(self) -> None:
        if not self._reflow_pending:
            self._reflow_pending = True
            QTimer.singleShot(0, self._reflow)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "spread"):
            self._schedule_reflow()

    def _active_index(self) -> int:
        focus = self.focusWidget()
        for index, page in enumerate(self.book.pages):
            widget = self.page_widgets.get(page.id)
            if widget and focus and (focus is widget.title_edit or focus is widget.body_edit or widget.body_edit.isAncestorOf(focus)):
                return index
        if self._last_active_page_id:
            for index, page in enumerate(self.book.pages):
                if page.id == self._last_active_page_id:
                    return index
        return self.spread_start

    def _focus_changed(self, old, current) -> None:
        if current is None:
            return
        for page in self.book.pages:
            widget = self.page_widgets.get(page.id)
            if widget and (current is widget.title_edit or current is widget.body_edit or widget.body_edit.isAncestorOf(current)):
                self._last_active_page_id = page.id
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

    def _format_heading(self) -> None:
        editor = self._active_editor()
        cursor = editor.textCursor()
        fmt = QTextBlockFormat()
        fmt.setHeadingLevel(2)
        cursor.setBlockFormat(fmt)
        editor.setFocus()

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
        name = uuid4().hex
        self.book.images[name] = data
        for widget in self.page_widgets.values():
            widget.body_edit.document().addResource(
                QTextDocument.ResourceType.ImageResource, QUrl(f"book-image:{name}"), image
            )
        index = self._active_index()
        self._page_widget(self.book.pages[index], index + 1).insert_image(name, image)

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
        self._schedule_reflow()

    def _update_title(self) -> None:
        name = self.path.stem if self.path else "未命名"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - Paperbound")

    def closeEvent(self, event) -> None:
        if self._maybe_save():
            event.accept()
        else:
            event.ignore()

    def _reflow(self) -> None:
        self._reflow_pending = False
        if self._building:
            return
        self._building = True
        changed = False
        try:
            for index in range(self.spread_start, min(self.spread_start + 2, len(self.book.pages))):
                changed = self._pull_forward(index) or changed
                changed = self._overflow_page(index) or changed
            if changed:
                count = len(self.book.pages)
                self.book.ensure_spread()
                if len(self.book.pages) != count:
                    self._show_spread()
        finally:
            self._building = False
        if changed:
            self._schedule_reflow()

    def _pull_forward(self, index: int) -> bool:
        next_index = index + 1
        if next_index >= len(self.book.pages) or self.book.pages[next_index].manual:
            return False
        source = self._page_widget(self.book.pages[index], index + 1).body_edit
        target_page = self.book.pages[next_index]
        target = self._page_widget(target_page, next_index + 1).body_edit
        if target.hasFocus() or not target.toPlainText().strip():
            return False
        limit = source.viewport().height() - 12
        first = target.document().firstBlock()
        first_height = first.layout().boundingRect().height()
        if source.document().size().height() + first_height + 16 > limit:
            return False
        end = first.next().position() if first.next().isValid() else target.document().characterCount() - 1
        cursor = QTextCursor(target.document())
        cursor.setPosition(0)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fragment = QTextDocumentFragment(cursor)
        if fragment.isEmpty():
            return False
        cursor.removeSelectedText()
        destination = QTextCursor(source.document())
        destination.movePosition(QTextCursor.MoveOperation.End)
        if source.toPlainText():
            destination.insertBlock()
        destination.insertFragment(fragment)
        self.book.pages[index].body = source.toMarkdown()
        target_page.body = target.toMarkdown()
        if not target.toPlainText().strip():
            widget = self.page_widgets.pop(target_page.id)
            widget.setParent(None)
            widget.deleteLater()
            del self.book.pages[next_index]
        self.dirty = True
        self._update_title()
        self._show_spread()
        return True

    def _overflow_page(self, index: int) -> bool:
        source = self._page_widget(self.book.pages[index], index + 1).body_edit
        limit = source.viewport().height() - 12
        if limit < 100:
            return False
        moved = False
        for _ in range(500):
            document = source.document()
            height = document.documentLayout().documentSize().height()
            if height <= limit:
                break
            next_index = index + 1
            if next_index == len(self.book.pages) or self.book.pages[next_index].manual:
                self.book.pages.insert(next_index, Page(manual=False))
            target = self._page_widget(self.book.pages[next_index], next_index + 1).body_edit
            block = document.lastBlock()
            start = block.position()
            if start == 0:
                if len(block.text()) < 2:
                    break
                fraction = max(0.2, min(0.8, limit / height * 0.8))
                start = max(1, int(len(block.text()) * fraction))
            cursor = QTextCursor(document)
            cursor.setPosition(start)
            cursor.setPosition(document.characterCount() - 1, QTextCursor.MoveMode.KeepAnchor)
            fragment = QTextDocumentFragment(cursor)
            if fragment.isEmpty():
                break
            was_typing_at_end = source.hasFocus() and source.textCursor().position() >= start
            cursor.removeSelectedText()
            if block.position() > 0 and cursor.block().text() == "":
                cursor.deletePreviousChar()
            destination = QTextCursor(target.document())
            destination.setPosition(0)
            had_content = bool(target.toPlainText())
            destination.insertFragment(fragment)
            if had_content:
                destination.insertBlock()
            moved = True
            self.book.pages[index].body = source.toMarkdown()
            self.book.pages[next_index].body = target.toMarkdown()
            self.dirty = True
            self._update_title()
            if was_typing_at_end:
                self.spread_start = next_index // 2 * 2
                self._show_spread()
                target.setFocus()
                target.moveCursor(QTextCursor.MoveOperation.End)
                break
        if moved:
            self._show_spread()
        return moved
