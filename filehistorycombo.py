import os
import sys
from pathlib import Path
from typing import Union

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QComboBox,
    QStyle,
)
from PySide6.QtGui import QAction

def get_unique_filepath(filepath: Union[str, Path]) -> str:
    path = Path(filepath)
    
    # If the file doesn't exist, return the original path as a string
    if not path.exists():
        return str(path)
    
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    
    counter = 1
    while True:
        # Construct new filename: original_name_copy_1.ext
        new_filename = f"{stem}_copy_{counter}{suffix}"
        new_path = parent / new_filename
        
        if not new_path.exists():
            return str(new_path)
        
        counter += 1

def get_unique_filename(filepath1: str, filepath2: str):
    if filepath1 != filepath2:
        return filepath1
    path = Path(filepath1)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    new_filename = f"{stem}_copy_{counter}{suffix}"
    return str(parent / new_filename)


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
        text = file_name.strip()

        if not text:
            self.lineEdit().setStyleSheet(
                "QLineEdit { border: 2px solid gray; }"
            )

            self.status_action.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_MessageBoxWarning
                )
            )

            self.setToolTip("Enter a file name")

            return

        # Plain names are resolved against base_dir; values containing path
        # separators (e.g. from the Browse dialog) are used as-is.
        is_path = "/" in text or "\\" in text
        full_path = text if is_path else os.path.join(self.base_dir, text)

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