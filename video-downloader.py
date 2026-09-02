import re
import shutil
import sys
import subprocess
import os
import shlex
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar, QPlainTextEdit,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QSpinBox,
    QComboBox, QStatusBar, QSizePolicy, QToolButton, QGridLayout,
    QCompleter, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QMenu,
)
from PySide6.QtCore import Qt, QSettings, QStringListModel, QModelIndex
from PySide6.QtGui import QFont, QPalette, QColor, QCloseEvent

from ffmpeg_worker import FFmpegWorker
from filehistorycombo import FileHistoryCombo


def find_ffmpeg():
    """Locate the ffmpeg executable.

    Search order: next to the running executable (standalone builds),
    current working directory (development layout with a local ffmpeg.exe),
    then PATH. Returns None when nothing is found.
    """
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates = []
    try:
        candidates.append(Path(sys.executable).parent / exe_name)
    except Exception:
        pass
    candidates.append(Path.cwd() / exe_name)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


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


class DownloadHistoryItem:
    """Represents a single download history entry"""
    def __init__(self, url="", output="", status="Queued", progress=0, timestamp=""):
        self.url = url
        self.output = output
        self.status = status  # Pending, Downloading, Downloaded, Failed, Cancelled
        self.progress = progress
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self):
        return {
            "url": self.url,
            "output": self.output,
            "status": self.status,
            "progress": self.progress,
            "timestamp": self.timestamp
        }

    def __eq__(self, other):
        if not isinstance(other, DownloadHistoryItem):
            return NotImplemented
        return self.url == other.url and self.output == other.output
    
    def __hash__(self):
        return hash((self.url, self.output))  # Only if objects are immutable 
    
    @classmethod
    def from_dict(cls, data):
        return cls(
            url=data.get("url", ""),
            output=data.get("output", ""),
            status=data.get("status", "Queued"),
            progress=data.get("progress", 0),
            timestamp=data.get("timestamp", "")
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M3U8 to MP4 Downloader")
        self.setMinimumSize(1100, 700)
        self.worker = None
        self.download_history = []
        self.waiting_list = []
        self._NumRowId = 0x100
        self.current_row = -1  # Track which row is currently downloading
        self.ffmpeg_path = find_ffmpeg()
        
        self.setup_ui()
        self.check_ffmpeg()
        self.load_history()

    def closeEvent(self, event: QCloseEvent):
        if self.is_running():
            answer = QMessageBox.question(
                self, "Download in progress",
                "A download is still running.\nCancel it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # stop() blocks until the process has exited (graceful 'q' first).
            self.worker.stop()
            self.worker.wait(10_000)
        self.saveSettings()
        self.save_history()
        event.accept()

    def loadSettings(self):
        settings = QSettings()
        listUrl = settings.value("list_url")
        if type(listUrl) is list:
            # Skip empty entries (old settings may contain a "" row from
            # a previous version of this code). The fields show their
            # placeholder text when empty; the clear buttons (\u274c) clear them.
            listUrl = [x for x in listUrl if x]
            self.url_input.addItems(listUrl)
            self.url_input.setCurrentIndex(-1)

        listOut = settings.value("list_out")
        if type(listOut) is list:
            listOut = [x for x in listOut if x]
            self.output_input.addItems(listOut)
            self.output_model.setStringList(listOut)
            self.output_input.setCurrentIndex(-1)

    def saveSettings(self):
        settings = QSettings()
        listUrls = []
        for x in range(self.url_input.count()):
            listUrls.append(self.url_input.itemText(x))
        settings.setValue("list_url", listUrls)

        listOut = []
        for x in range(self.output_input.count()):
            listOut.append(self.output_input.itemText(x))
        settings.setValue("list_out", listOut)

    def load_history(self):
        """Load download history from settings"""
        settings = QSettings()
        history_data = settings.value("download_history", [])
        
        if isinstance(history_data, list):
            self.download_history = []
            self.history_table.setRowCount(0)
            
            for item_data in history_data:
                if isinstance(item_data, dict):
                    item = DownloadHistoryItem.from_dict(item_data)

                    if item in self.download_history:
                        continue
                    # Reset "Downloading" status to "Failed" or "Pending" on load
                    if item.status == "Downloading":
                        item.status = "Failed"
                        item.progress = 0
                    self.add_history_row(item.output, item.url, item.status)

    def save_history(self):
        """Save download history to settings"""
        settings = QSettings()
        history_data = [item.to_dict() for item in self.download_history]
        settings.setValue("download_history", history_data)

    def addOut(self, val):
        # Record the value in the dropdown history without rebuilding the combo.
        # clear() + addItems() on an editable combo snaps it back to index 0 and
        # overwrites the line edit with the first entry (often "" or a stale value);
        # inserting a row leaves the current text and selection untouched.
        if self.output_input.findText(val) != -1:
            return
        self.output_input.insertItem(self.output_input.count(), val)
        # Keep the completer model in sync with the combo (QStringListModel has
        # no single-item insert; resync the whole list).
        self.output_model.setStringList(
            [self.output_input.itemText(i) for i in range(self.output_input.count())]
        )

    def addUrl(self, url):
        if self.url_input.findText(url) != -1:
            return
        self.url_input.insertItem(self.url_input.count(), url)

    def clear_url(self):
        self.url_input.setCurrentText("")   
        
    def clear_out(self):
        self.output_input.setCurrentText("")   

    def clipboard_paste(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data.hasText():
            text = clipboard.text()
            self.url_input.setCurrentText(text)

    def historyDoubleClick(self, index: QModelIndex):
        row = index.row()
        if row >= 0 and row < len(self.download_history):
            item = self.download_history[row]
            self.url_input.setCurrentText(item.url)
            self.output_input.setCurrentText(item.output)

    def show_context_menu(self, pos):
        item = self.history_table.itemAt(pos)
        if(item is None):
            return
        
        row = item.row()
        column = item.column()

        menu = QMenu(self)

        # action_info = menu.addAction(
        #     f"Cell [{row}:{column}]"
        # )
        action_copy_file = menu.addAction("Copy File Name")
        action_copy_ref  = menu.addAction("Copy Reference")
        action_copy_to_file_place = menu.addAction("Copy File Name to Output")

        action_remove = menu.addAction("Remove row")
        
        action = menu.exec(
            self.history_table.viewport().mapToGlobal(pos)
        )

        if action == action_remove:
            name_item = self.history_table.item(row, 0)
            row_id = int(name_item.data(self._NumRowId)) if name_item is not None else -1
            if row_id == self.current_row:
                # The active download keeps running but loses its UI tracking.
                self.current_row = -1
            self.history_table.removeRow(row)
            del self.download_history[row]
            self.save_history()
        elif action == action_copy_file:
            name = self.download_history[row].output
            QApplication.clipboard().setText(name)
        elif action == action_copy_ref:
            name = self.download_history[row].url
            QApplication.clipboard().setText(name)
        elif action == action_copy_to_file_place:
            name = self.download_history[row].output
            self.output_input.setCurrentText(name)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
       
        # Input Section
        input_group = QGroupBox("Source & Destination")
        input_layout = QGridLayout(input_group)
        
        input_layout.addWidget(QLabel("M3U8 URL:"), 0, 0)
        self.url_input = ComboWithPlaceholder()
        self.url_input.setEditable(True)
        self.url_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.url_input.setPlaceholderText("https://example.com/playlist.m3u8")
        self.url_input.currentTextChanged.connect(self.suggest_filename)
        input_layout.addWidget(self.url_input, 0, 1)
        
        self.clear_btn = QToolButton()
        self.clear_btn.setText("❌")
        self.clear_btn.setToolTip("Clear url")
        self.clear_btn.clicked.connect(self.clear_url)
        input_layout.addWidget(self.clear_btn, 0, 2)

        # self.btn_paste = QPushButton("Paste & Auto-name")
        # self.btn_paste.clicked.connect(self.paste_and_suggest)
        # input_layout.addWidget(self.btn_paste, 0, 3)

        self.clipboard_btn = QToolButton()
        self.clipboard_btn.setText("📋")
        self.clipboard_btn.setToolTip("Paste from clipboard")
        self.clipboard_btn.clicked.connect(self.clipboard_paste)
        input_layout.addWidget(self.clipboard_btn, 0, 3)

        input_layout.addWidget(QLabel("Output File:"), 1, 0)
        self.output_input = FileHistoryCombo(".") #ComboWithPlaceholder()
        self.output_input.setEditable(True)
        self.output_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.output_input.setPlaceholderText("output.mp4")
        self.output_model = QStringListModel([])
        self.output_completer = QCompleter(self.output_model)
        self.output_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.output_input.setCompleter(self.output_completer)
        input_layout.addWidget(self.output_input, 1, 1)

        self.clear_btn_out = QToolButton()
        self.clear_btn_out.setText("❌")
        self.clear_btn_out.setToolTip("Clear output")
        self.clear_btn_out.clicked.connect(self.clear_out)
        input_layout.addWidget(self.clear_btn_out, 1, 2)

        self.btn_browse = QToolButton()
        self.btn_browse.setText("📂")
        self.btn_browse.setToolTip("Browse...")
        self.btn_browse.clicked.connect(self.browse_output)
        input_layout.addWidget(self.btn_browse, 1, 3)
        
        main_layout.addWidget(input_group)
        
        # Options Section
        options_group = QGroupBox("Encoding Options")
        options_layout = QVBoxLayout(options_group)
        
        codec_layout = QHBoxLayout()
        
        self.copy_checkbox = QCheckBox("Copy streams (-c copy) - Fast, no re-encoding")
        self.copy_checkbox.setChecked(True)
        self.copy_checkbox.stateChanged.connect(self.toggle_encoding_options)
        codec_layout.addWidget(self.copy_checkbox)
        
        codec_layout.addWidget(QLabel("Audio Filter:"))
        self.audio_filter = QComboBox()
        self.audio_filter.addItems(["aac_adtstoasc (default)", "none"])
        self.audio_filter.setEnabled(True)
        codec_layout.addWidget(self.audio_filter)
        
        codec_layout.addStretch()
        options_layout.addLayout(codec_layout)
        
        quality_layout = QHBoxLayout()
        quality_layout.addWidget(QLabel("Quality (CRF):"))
        self.crf_spinbox = QSpinBox()
        self.crf_spinbox.setRange(0, 51)
        self.crf_spinbox.setValue(23)
        self.crf_spinbox.setToolTip("0=lossless, 23=default, 51=worst")
        self.crf_spinbox.setEnabled(False)
        quality_layout.addWidget(self.crf_spinbox)
        
        quality_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"])
        self.preset_combo.setCurrentText("medium")
        self.preset_combo.setEnabled(False)
        quality_layout.addWidget(self.preset_combo)
        
        quality_layout.addStretch()
        options_layout.addLayout(quality_layout)
        
        extra_layout = QHBoxLayout()
        extra_layout.addWidget(QLabel("Extra Args:"))
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("-bsf:a aac_adtstoasc -vf scale=1920:1080")
        extra_layout.addWidget(self.extra_args)
        options_layout.addLayout(extra_layout)
        
        main_layout.addWidget(options_group)
        
        # Progress Section
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # History Table + Log Output in a splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # History Table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(3)
        self.history_table.setHorizontalHeaderLabels(["Output Name", "URL", "Status"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setMinimumWidth(350)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(
            self.show_context_menu
        )
        self.history_table.doubleClicked.connect(self.historyDoubleClick)
        self.splitter.addWidget(self.history_table)
        
        # Log Section
        self.log_output = QPlainTextEdit()
        self.log_output.setMaximumBlockCount(1000)
        self.log_output.setFont(QFont("Consolas", 9))
        self.log_output.setPlaceholderText("FFmpeg output will appear here...")
        self.splitter.addWidget(self.log_output)
        
        # Set splitter proportions (30% table, 70% log)
        self.splitter.setSizes([650, 350])
        main_layout.addWidget(self.splitter, stretch=1)
        
        # Controls
        control_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("▶ Add to Queue")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.btn_start.clicked.connect(self.start_download)
        control_layout.addWidget(self.btn_start)
        
        self.btn_cancel = QPushButton("⏹ Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
        self.btn_cancel.clicked.connect(self.cancel_download)
        control_layout.addWidget(self.btn_cancel)
        
        self.btn_clear = QPushButton("Clear Log")
        self.btn_clear.clicked.connect(self.log_output.clear)
        control_layout.addWidget(self.btn_clear)
        
        self.btn_clear_history = QPushButton("Clear History")
        self.btn_clear_history.clicked.connect(self.clear_history)
        control_layout.addWidget(self.btn_clear_history)
        
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self.loadSettings()
        
    def toggle_encoding_options(self, state):
        copy_enabled = state == Qt.CheckState.Checked.value
        self.crf_spinbox.setEnabled(not copy_enabled)
        self.preset_combo.setEnabled(not copy_enabled)
        self.audio_filter.setEnabled(copy_enabled)
        
    def suggest_filename(self, text):
        url = self.url_input.currentText().strip()
        if not url:
            return
            
        try:
            clean_url = url.split('?')[0]
            path = Path(clean_url)
            name = path.stem
            
            if name and name not in ['index', 'playlist', 'master', 'stream']:
                suggested = f"{name}.mp4"
                if not self.output_input.currentText():
                    self.output_input.setCurrentText(suggested)
        except:
            pass
    
    def paste_and_suggest(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.url_input.setCurrentText(text)
            self.suggest_filename()
            
    def browse_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save MP4 File", "", "MP4 Files (*.mp4);;All Files (*)"
        )
        if file_path:
            if not file_path.endswith('.mp4'):
                file_path += '.mp4'
            self.output_input.setCurrentText(file_path)
    
    def check_ffmpeg(self):
        if not self.ffmpeg_path:
            QMessageBox.critical(
                self, "FFmpeg Not Found",
                "FFmpeg was not found next to the app or in PATH.\n\n"
                "Please install FFmpeg first:\n"
                "• Windows: Download from ffmpeg.org and add to PATH\n"
                "• macOS: brew install ffmpeg\n"
                "• Linux: sudo apt install ffmpeg"
            )
            self.btn_start.setEnabled(False)
            self.status_bar.showMessage("FFmpeg not found - downloads disabled")
            return
        try:
            result = subprocess.run([self.ffmpeg_path, '-version'], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            version_line = result.stdout.split('\n')[0]
            self.status_bar.showMessage(f"FFmpeg detected: {version_line[:50]}...")
        except OSError as e:
            QMessageBox.critical(self, "FFmpeg Error", f"Failed to run ffmpeg:\n{e}")
            self.btn_start.setEnabled(False)
    
    def add_history_row(self, output_name, url, status="Queued"):
        """Add a new row to the history table and return the row index."""
        history_item = DownloadHistoryItem(url=url, output=output_name, status=status, progress=0)

        for i, item in enumerate(self.download_history):
            if item == history_item:
                status_item = self.history_table.item(i, 2)
                self.history_table.scrollToItem(status_item)
                return i

        row = self.history_table.rowCount()
        self.history_table.insertRow(row)
        
        # Output Name
        name_item = QTableWidgetItem(output_name)
        name_item.setToolTip(output_name)
        name_item.setData(self._NumRowId, row)
        self.history_table.setItem(row, 0, name_item)
        
        # URL
        url_item = QTableWidgetItem(url)
        url_item.setToolTip(url)
        self.history_table.setItem(row, 1, url_item)
        
        # Status
        status_item = QTableWidgetItem(status)
        status_item.setToolTip(status)
        self.history_table.setItem(row, 2, status_item)
        
        # Scroll to the new row
        self.history_table.scrollToItem(status_item)

        self.download_history.append(history_item)
                
        return row
    
    def update_history_status(self, row, status):
        """Update the status column of a specific row."""
        
        target = -1
        for i in range(self.history_table.rowCount()):
            item = self.history_table.item(i, 0)
            if item is not None and int(item.data(self._NumRowId)) == row:
                target = i
                break
        # No match (e.g. the active row was removed from the table): skip
        # instead of falling back to a possibly wrong index.
        if 0 <= target < len(self.download_history):
            self.history_table.item(target, 2).setText(status)
            self.download_history[target].status = status
    
    def clear_history(self):
        """Clear all rows from the history table."""
        self.history_table.setRowCount(0)
        self.download_history = []
        self.current_row = -1

    def build_cmd(self, url, output):
        cmd = ['-hide_banner', '-stats']  # -stats forces progress output
        if url.lower().startswith(("http://", "https://")):
            # Resilience against flaky HLS sources (input options)
            cmd.extend(['-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5'])
        cmd.extend(['-user_agent', "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"])
        cmd.extend(['-i', url])
        
        if self.copy_checkbox.isChecked():
            cmd.extend(['-c', 'copy'])
            if self.audio_filter.currentText().startswith('aac_adtstoasc'):
                cmd.extend(['-bsf:a', 'aac_adtstoasc'])
        else:
            cmd.extend(['-c:v', 'libx264'])
            cmd.extend(['-crf', str(self.crf_spinbox.value())])
            cmd.extend(['-preset', self.preset_combo.currentText()])
            cmd.extend(['-c:a', 'aac', '-b:a', '192k'])
        
        # Add extra arguments
        extra = self.extra_args.text().strip()
        if extra:
            try:
                extra_list = shlex.split(extra)
                cmd.extend(extra_list)
            except ValueError as e:
                raise ValueError(f"Invalid extra arguments: {e}")
        
        cmd.extend(['-y', '-progress', 'pipe:1'])  # Output progress to stdout
        cmd.append(output)
        return cmd
    
    def build_command(self):
        url = self.url_input.currentText().strip()
        output = self.output_input.currentText().strip() or "output.mp4"
        # Only force .mp4 when no known media extension is present, so that
        # e.g. ".mkv" (useful for HLS streams with AC-3 audio) is respected.
        if not re.search(r'\.(mp4|mkv|mov|m4v|webm|ts|avi)$', output, re.IGNORECASE):
            output += ".mp4"

        if not url:
            raise ValueError("Please enter a valid M3U8 URL")
        
        self.addUrl(url)
        self.addOut(output)
        self.saveSettings()
        
        # Build command
        cmd = self.build_cmd(url, output)
        
        return cmd, url, output
    
    def is_running(self):
        return not self.worker is None and self.worker.is_running()
    
    def check_waiting_list(self):
        if not self.waiting_list:
            return

        item = self.waiting_list.pop(0)
        if self.waiting_list:
            self.status_bar.showMessage(f"Queue: {len(self.waiting_list)} waiting")
        if not self.is_running():
            self._start_download(item.url, item.output)

    def confirm_overwrite(self, output: str) -> bool:
        """Ask the user before overwriting an existing file.

        Returns True when the download may proceed (file absent or overwrite
        accepted), False when the user declined and the download must abort.
        """
        if not os.path.exists(output):
            return True
        answer = QMessageBox.question(
            self, "File exists",
            f'The file "{output}" already exists.\nOverwrite it?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _start_download(self, url, output):
        try:           
            if not self.confirm_overwrite(output):
                return
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.btn_cancel.setEnabled(True)
            
            # Add to history table
            output_name = os.path.basename(output)
            self.current_row = self.add_history_row(output_name, url, "Downloading...")
            
            cmd_args = self.build_cmd(url, output)

            self.worker = FFmpegWorker(cmd_args, self.current_row, ffmpeg_path=self.ffmpeg_path)
            self.worker.progress.connect(self.handle_progress)
            self.worker.status.connect(self.status_bar.showMessage)
            self.worker.log.connect(self.append_log)
            self.worker.duration_found.connect(self.handle_duration)
            self.worker.finished.connect(self.download_finished)
            self.worker.start()

        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    
    def start_download(self):
        try:
            cmd_args, url, output = self.build_command()

            if not self.confirm_overwrite(output):
                return

            if self.is_running():
                item = DownloadHistoryItem(url, output)
                self.waiting_list.append(item)
                # Same (url, basename) key as _start_download so the queued row
                # is reused instead of duplicated when the download starts.
                self.add_history_row(output_name=os.path.basename(output), url=url, status="Queued")
                return

            self.log_output.appendPlainText(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            self._start_download(url, output)
            
        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
    
    def handle_progress(self, value):
        """Handle progress updates from worker."""
        self.progress_bar.setValue(value)
        if(self.current_row >= 0):
            self.update_history_status(self.current_row, f"Downloading... {value}%")

    def handle_duration(self, found: bool):
        """Switch the progress bar between determinate and indeterminate mode."""
        if found:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        else:
            # Live stream without a known duration - spin instead of freezing at 0%.
            self.progress_bar.setRange(0, 0)
    
    def append_log(self, text):
        self.log_output.insertPlainText(text)
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def cancel_download(self):
        if self.worker:
            self.worker.stop()
            self.status_bar.showMessage("Cancelling...")
            if self.current_row >= 0:
                self.update_history_status(self.current_row, "Cancelled")
        self.waiting_list = []
    
    def download_finished(self, success, message):
        self.btn_cancel.setEnabled(False)

        lines = (message or "").splitlines()
        first_line = lines[0] if lines else ""

        if success:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            if self.current_row >= 0:
                self.update_history_status(self.current_row, "Downloaded")
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            if self.current_row >= 0:
                self.update_history_status(self.current_row, f"Failed: {first_line[:50]}")
            QMessageBox.warning(self, "Download Status", message)

        self.status_bar.showMessage(first_line)
        self.save_history()
        self.current_row = -1
        self.worker = None

        self.check_waiting_list()


if __name__ == '__main__':
    app = QApplication(sys.argv)

    app.setOrganizationName("VideoTools")
    app.setApplicationName("MP4 Downloader")
    
    # Optional dark theme
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(142, 45, 197).lighter())
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())