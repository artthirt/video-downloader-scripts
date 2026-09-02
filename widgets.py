"""Reusable custom widgets."""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QPlainTextEdit, QPushButton,
    QVBoxLayout, QHBoxLayout, QCheckBox,
)
from PySide6.QtGui import QFont


class ComboWithPlaceholder(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def setPlaceholderText(self, text: str):
        """Override to set placeholder on the internal line edit"""
        if self.lineEdit():
            self.lineEdit().setPlaceholderText(text)
        else:
            # Fallback for non-editable mode
            super().setPlaceholderText(text)


class LogDialog(QDialog):
    """A separate, non-modal window that shows the streaming FFmpeg log.

    Created once and kept alive across show/hide so the log history is retained.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FFmpeg Log")
        self.resize(720, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(2000)
        self.text.setFont(QFont("Consolas", 9))
        self.text.setPlaceholderText("FFmpeg output will appear here...")
        layout.addWidget(self.text)

        bottom = QHBoxLayout()
        self.follow = QCheckBox("Follow (auto-scroll)")
        self.follow.setChecked(True)
        bottom.addWidget(self.follow)
        bottom.addStretch()
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.clear)
        bottom.addWidget(btn_clear)
        layout.addLayout(bottom)

    def append(self, text):
        """Append a line and, if following, keep the view pinned to the end."""
        self.text.insertPlainText(text)
        if self.follow.isChecked():
            sb = self.text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def clear(self):
        self.text.clear()
