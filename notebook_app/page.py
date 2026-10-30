from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QTextBlockFormat, QTextCursor, QTextDocument, QTextImageFormat, QTextListFormat
from PySide6.QtWidgets import QFrame, QLineEdit, QTextEdit, QVBoxLayout

from notebook_app.model import Page


class PageEditor(QTextEdit):
    def keyPressEvent(self, event) -> None:
        if event.text() == " ":
            cursor = self.textCursor()
            block = cursor.block()
            prefix = block.text()[: cursor.positionInBlock()]
            if prefix in ("#", "##", "###", "-"):
                cursor.setPosition(block.position())
                cursor.setPosition(block.position() + len(prefix), QTextCursor.MoveMode.KeepAnchor)
                cursor.removeSelectedText()
                if prefix == "-":
                    cursor.createList(QTextListFormat.Style.ListDisc)
                else:
                    block_format = QTextBlockFormat()
                    block_format.setHeadingLevel(len(prefix))
                    cursor.setBlockFormat(block_format)
                self.setTextCursor(cursor)
                return
        super().keyPressEvent(event)


class PageWidget(QFrame):
    changed = Signal()

    def __init__(self, page: Page, number: int, paper_style: str, images: dict[str, bytes]) -> None:
        super().__init__()
        self.page = page
        self.paper_style = paper_style
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
        for name, data in images.items():
            image = QImage.fromData(data)
            if not image.isNull():
                self.body_edit.document().addResource(
                    QTextDocument.ResourceType.ImageResource, QUrl(f"book-image:{name}"), image
                )
        self.body_edit.setMarkdown(page.body)
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
        self.changed.emit()

    def set_number(self, number: int) -> None:
        self.number = number
        self.update()

    def set_paper_style(self, style: str) -> None:
        self.paper_style = style
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
            for y in range(128, self.height() - 35, 28):
                painter.drawLine(42, y, self.width() - 40, y)
        if self.paper_style == "grid":
            for x in range(48, self.width() - 35, 28):
                painter.drawLine(x, 120, x, self.height() - 35)
        painter.setPen(QColor("#9a9f98"))
        font = QFont(self.font())
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(0, self.height() - 14, self.width(), 12, Qt.AlignmentFlag.AlignHCenter, str(self.number))
