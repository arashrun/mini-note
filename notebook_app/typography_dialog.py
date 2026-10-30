from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QFontComboBox, QFormLayout, QSpinBox, QVBoxLayout,
)

from notebook_app.model import Typography


class TypographyDialog(QDialog):
    def __init__(self, typography: Typography, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("正文排版")
        self.setMinimumWidth(330)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.system_font = QCheckBox("跟随系统字体")
        self.system_font.setChecked(not typography.font_family)
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont(typography.font_family or QApplication.font().family()))
        self.font_family.setEnabled(bool(typography.font_family))
        self.system_font.toggled.connect(lambda checked: self.font_family.setEnabled(not checked))
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 28)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(typography.font_size)
        self.line_spacing = QSpinBox()
        self.line_spacing.setRange(100, 220)
        self.line_spacing.setSuffix("%")
        self.line_spacing.setValue(typography.line_spacing)
        form.addRow("字体", self.system_font)
        form.addRow("选择字体", self.font_family)
        form.addRow("字号", self.font_size)
        form.addRow("行距", self.line_spacing)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_typography(self) -> Typography:
        return Typography(
            "" if self.system_font.isChecked() else self.font_family.currentFont().family(),
            self.font_size.value(),
            self.line_spacing.value(),
        )
