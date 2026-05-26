import os
import sys

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QComboBox,
    QStyle,
)
from PySide6.QtGui import QAction

class FileHistoryCombo(QComboBox):
    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)

        self.base_dir = base_dir

        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)

        self.status_action = self.lineEdit().addAction(
            self.style().standardIcon(
                QStyle.StandardPixmap.SP_MessageBoxInformation
            ),
            self.lineEdit().ActionPosition.TrailingPosition,
        )

        self.lineEdit().textChanged.connect(self.update_state)

        self.update_state(self.currentText())

    def setPlaceholderText(self, text: str):
        """Override to set placeholder on the internal line edit"""
        if self.lineEdit():
            self.lineEdit().setPlaceholderText(text)
        else:
            # Fallback for non-editable mode
            super().setPlaceholderText(text)

    def update_state(self, file_name: str):
        valid = (
            bool(file_name)
            and "/" not in file_name
            and "\\" not in file_name
        )

        if not valid:
            self.lineEdit().setStyleSheet(
                "QLineEdit { border: 2px solid gray; }"
            )

            self.status_action.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_MessageBoxWarning
                )
            )

            self.setToolTip("Invalid file name")

            return

        full_path = os.path.join(self.base_dir, file_name)

        if os.path.isfile(full_path):
            self.lineEdit().setStyleSheet(
                "QLineEdit { border: 2px solid red; }"
            )

            self.status_action.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_DialogCancelButton
                )
            )

            self.setToolTip("File already exists")

        else:
            self.lineEdit().setStyleSheet(
                "QLineEdit { border: 2px solid green; }"
            )

            self.status_action.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_DialogApplyButton
                )
            )

            self.setToolTip("File name is available")

    def add_history_item(self):
        text = self.currentText().strip()

        if not text:
            return

        # avoid duplicates
        index = self.findText(text)

        if index >= 0:
            self.removeItem(index)

        self.insertItem(0, text)
        self.setCurrentIndex(0)