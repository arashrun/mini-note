import re

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QDesktopServices, QFont, QFontMetricsF, QImage, QPainter, QPen, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextImageFormat
from PySide6.QtWidgets import QFrame, QLineEdit, QTextEdit, QVBoxLayout

from notebook_app.model import Page, Typography


class PageEditor(QTextEdit):
    imagePasted = Signal(object, bytes)
    imageDoubleClicked = Signal(str)
    deactivateStyleRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.deactivateStyleRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)
        if event.text() == ")":
            self._format_typed_link()

    def _format_typed_link(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        match = re.search(r"\[([^\]]+)\]\(([^)]+)\)$", block.text()[: cursor.positionInBlock()])
        if not match:
            return
        start = block.position() + match.start()
        end = block.position() + match.end()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        label, url = match.group(1), match.group(2)
        cursor.insertText(label)
        cursor.setPosition(start)
        cursor.setPosition(start + len(label), QTextCursor.MoveMode.KeepAnchor)
        from PySide6.QtGui import QTextCharFormat
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url)
        fmt.setForeground(QColor("#1769aa"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
        cursor.mergeCharFormat(fmt)
        cursor.setPosition(start + len(label))
        self.setTextCursor(cursor)
        reset = QTextCharFormat()
        reset.setAnchor(False)
        reset.setForeground(QColor("#26322f"))
        reset.setUnderlineStyle(QTextCharFormat.UnderlineStyle.NoUnderline)
        self.setCurrentCharFormat(reset)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cursor = self.cursorForPosition(event.position().toPoint())
            url = cursor.charFormat().anchorHref()
            if url:
                QDesktopServices.openUrl(QUrl(url))
                event.accept()
                return
        super().mousePressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            if isinstance(image, QImage) and not image.isNull():
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                payload = QByteArray()
                buffer = QBuffer(payload)
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, "PNG")
                buffer.close()
                self.imagePasted.emit(image, bytes(payload))
                return
        super().insertFromMimeData(source)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasImage() or event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasImage():
            self.insertFromMimeData(event.mimeData())
            event.acceptProposedAction()
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                image = QImage(url.toLocalFile())
                if not image.isNull():
                    from pathlib import Path
                    self.imagePasted.emit(image, Path(url.toLocalFile()).read_bytes())
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        cursor = self.cursorForPosition(event.position().toPoint())
        char_format = cursor.charFormat()
        if char_format.isImageFormat():
            name = QUrl(char_format.toImageFormat().name()).path().strip("/")
            if not name:
                name = char_format.toImageFormat().name().split(":")[-1]
            self.imageDoubleClicked.emit(name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class PageWidget(QFrame):
    changed = Signal()
    contextMenuRequested = Signal(object)

    def __init__(self, page: Page, number: int, paper_style: str, images: dict[str, bytes], typography: Typography) -> None:
        super().__init__()
        self.page = page
        self.paper_style = paper_style
        self.typography = typography
        self.setObjectName("paperPage")
        self.setMinimumWidth(300)
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 44, 46, 34)
        layout.setSpacing(14)
        self.title_edit = QLineEdit(page.title)
        self.title_edit.setPlaceholderText("章节标题")
        self.title_edit.setMaxLength(120)
        self.title_edit.setObjectName("pageTitle")
        self.body_edit = PageEditor()
        self.body_edit.setAcceptRichText(True)
        self.body_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_edit.setPlaceholderText("开始写作...")
        self.body_edit.setFrameShape(QFrame.Shape.NoFrame)
        self.body_edit.setObjectName("pageBody")
        self.body_edit.verticalScrollBar().valueChanged.connect(self.update)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.title_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.body_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda point: self.contextMenuRequested.emit(self.mapToGlobal(point)))
        self.title_edit.customContextMenuRequested.connect(lambda point: self.contextMenuRequested.emit(self.title_edit.mapToGlobal(point)))
        self.body_edit.customContextMenuRequested.connect(lambda point: self.contextMenuRequested.emit(self.body_edit.mapToGlobal(point)))
        for name, data in images.items():
            image = QImage.fromData(data)
            if not image.isNull():
                self.body_edit.document().addResource(
                    QTextDocument.ResourceType.ImageResource, QUrl(f"book-image:{name}"), image
                )
        self.body_edit.setHtml(page.html) if page.html else self.body_edit.setMarkdown(page.body)
        for name, data in images.items():
            image = QImage.fromData(data)
            if not image.isNull():
                self.body_edit.document().addResource(
                    QTextDocument.ResourceType.ImageResource, QUrl(f"book-image:{name}"), image
                )
        self.apply_typography(typography)
        layout.addWidget(self.title_edit)
        layout.addWidget(self.body_edit, 1)
        self.number = number
        self.title_edit.textChanged.connect(self._title_changed)
        self.body_edit.textChanged.connect(self._body_changed)

    def _title_changed(self, value: str) -> None:
        self.page.title = value
        self.changed.emit()

    def _body_changed(self) -> None:
        self.page.body = self.body_edit.toMarkdown()
        self.page.html = self.body_edit.toHtml()
        self.changed.emit()

    def set_number(self, number: int) -> None:
        self.number = number
        self.update()

    def set_paper_style(self, style: str) -> None:
        self.paper_style = style
        self.update()

    def apply_typography(self, typography: Typography) -> None:
        self.typography = typography
        editor = self.body_edit
        document = editor.document()
        cursor = editor.textCursor()
        typing_format = editor.currentCharFormat()
        scroll_value = editor.verticalScrollBar().value()
        font = QFont(editor.font())
        if typography.font_family:
            font.setFamily(typography.font_family)
        font.setPointSize(typography.font_size)

        document.setUndoRedoEnabled(False)
        try:
            editor.setFont(font)
            document.setDefaultFont(font)
            all_text = QTextCursor(document)
            all_text.select(QTextCursor.SelectionType.Document)
            character = QTextCharFormat()
            character.setFontFamilies([font.family()])
            character.setFontPointSize(typography.font_size)
            block = QTextBlockFormat()
            block.setLineHeight(float(typography.line_spacing), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            all_text.mergeCharFormat(character)
            all_text.mergeBlockFormat(block)
            editor.setTextCursor(cursor)
            if not cursor.hasSelection():
                typing_format.setFontFamilies([font.family()])
                typing_format.setFontPointSize(typography.font_size)
                editor.setCurrentCharFormat(typing_format)
        finally:
            document.setUndoRedoEnabled(True)
        if editor.hasFocus():
            editor.ensureCursorVisible()
        else:
            editor.verticalScrollBar().setValue(scroll_value)
        self._body_changed()
        self.update()

    def insert_image(self, name: str, image) -> None:
        url = f"book-image:{name}"
        self.body_edit.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), image)
        image_format = QTextImageFormat()
        image_format.setName(url)
        width = min(image.width(), max(120, self.body_edit.viewport().width() - 24))
        image_format.setWidth(width)
        image_format.setHeight(round(image.height() * width / image.width()))
        self.body_edit.textCursor().insertImage(image_format)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#fffdf7"))
        painter.setPen(QPen(QColor("#e2e0d5"), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QPen(QColor("#d5d8ce"), 1))
        if self.paper_style in ("ruled", "grid"):
            if self.paper_style == "ruled":
                metrics = QFontMetricsF(self.body_edit.font())
                step = max(22, round(metrics.height() * self.typography.line_spacing / 100))
            else:
                step = 28
            body_top = self.body_edit.geometry().top()
            first_line = body_top + round(QFontMetricsF(self.body_edit.font()).ascent()) + 8
            first_line -= self.body_edit.verticalScrollBar().value() % step
            for y in range(first_line, self.height() - 35, step):
                painter.drawLine(42, y, self.width() - 40, y)
        if self.paper_style == "grid":
            for x in range(48, self.width() - 35, 28):
                painter.drawLine(x, 120, x, self.height() - 35)
        painter.setPen(QColor("#9a9f98"))
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(0, self.height() - 14, self.width(), 12, Qt.AlignmentFlag.AlignHCenter, str(self.number))
