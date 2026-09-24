import re
import sys
import subprocess
import os
import shlex
from pathlib import Path
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QProgressBar,
    QFileDialog, QMessageBox, QGroupBox, QCheckBox, QSpinBox,
    QComboBox, QStatusBar, QSizePolicy, QToolButton, QGridLayout,
    QCompleter, QTableWidget, QTableWidgetItem, QHeaderView,
    QMenu,
)
from PySide6.QtCore import Qt, QSettings, QStringListModel, QModelIndex
from PySide6.QtGui import QPalette, QColor, QCloseEvent, QIcon

from filehistorycombo import FileHistoryCombo
from models import DownloadHistoryItem, find_ffmpeg
from widgets import ComboWithPlaceholder, LogDialog
from download_queue import DownloadQueue


def pick_icon_path():
    """Locate the app icon next to the script (dev) or the exe (standalone)."""
    base = Path(__file__).resolve().parent
    candidates = [
        base / "assets" / "icon.ico",
        base / "assets" / "icon.png",
        base / "icon.ico",
        base / "icon.png",
    ]
    try:
        exe_dir = Path(sys.executable).parent
        candidates += [
            exe_dir / "assets" / "icon.ico",
            exe_dir / "assets" / "icon.png",
            exe_dir / "icon.ico",
            exe_dir / "icon.png",
        ]
    except Exception:
        pass
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("M3U8 to MP4 Downloader")
        self.setMinimumSize(1100, 700)
        self.download_history = []
        self._NumRowId = 0x100
        self._row_id_seq = 0      # monotonic opaque row id (never reused)
        self._active_pct = {}     # row_id -> last determinate percent
        self._active_live = {}    # row_id -> True when duration is unknown (live)
        self.ffmpeg_path = find_ffmpeg()

        self.setup_ui()
        self.check_ffmpeg()
        self._init_queue()
        self.load_history()

    # ---- concurrency engine ------------------------------------------------
    def _init_queue(self):
        self.queue = DownloadQueue(self.ffmpeg_path, self.build_cmd, parent=self)
        self.queue.started.connect(self._row_started)
        self.queue.progress.connect(self._row_progress)
        self.queue.live.connect(self._row_live)
        self.queue.finished.connect(self._row_finished)
        self.queue.log.connect(self.append_log)
        self.queue.state_changed.connect(self._update_state)
        self.queue.set_max_concurrent(self.max_spinbox.value())
        self.max_spinbox.valueChanged.connect(self.queue.set_max_concurrent)

    def is_running(self):
        return self.queue is not None and self.queue.is_running()

    def closeEvent(self, event: QCloseEvent):
        if self.queue and (self.queue.is_running() or self.queue.waiting_count() > 0):
            answer = QMessageBox.question(
                self, "Download in progress",
                "A download is still running.\nCancel it and exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # stop_all() blocks until every ffmpeg process has exited.
            self.queue.stop_all()
        self.saveSettings()
        self.save_history()
        event.accept()

    def loadSettings(self):
        settings = QSettings()
        listUrl = settings.value("list_url")
        if type(listUrl) is list:
            # Skip empty entries (old settings may contain a "" row from
            # a previous version of this code). The fields show their
            # placeholder text when empty; the clear buttons (❌) clear them.
            listUrl = [x for x in listUrl if x]
            self.url_input.addItems(listUrl)
            self.url_input.setCurrentIndex(-1)

        listOut = settings.value("list_out")
        if type(listOut) is list:
            listOut = [x for x in listOut if x]
            self.output_input.addItems(listOut)
            self.output_model.setStringList(listOut)
            self.output_input.setCurrentIndex(-1)

        maxc = settings.value("max_concurrent", 1)
        try:
            self.max_spinbox.setValue(int(maxc))
        except (TypeError, ValueError):
            self.max_spinbox.setValue(1)

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

        settings.setValue("max_concurrent", self.max_spinbox.value())

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

        action_copy_file = menu.addAction("Copy File Name")
        action_copy_ref  = menu.addAction("Copy Reference")
        action_copy_to_file_place = menu.addAction("Copy File Name to Output")

        menu.addSeparator()

        name_item = self.history_table.item(row, 0)
        row_id = int(name_item.data(self._NumRowId)) if name_item is not None else -1
        action_cancel = menu.addAction("Cancel")
        action_cancel.setEnabled(row_id != -1 and self.queue.is_row_active_or_waiting(row_id))

        action_remove = menu.addAction("Remove row")

        action = menu.exec(
            self.history_table.viewport().mapToGlobal(pos)
        )

        if action == action_remove:
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
        elif action == action_cancel:
            self.queue.cancel_row(row_id)
            # Waiting rows are dropped immediately (no finished signal for them),
            # so reflect the cancellation right away; active rows are updated by
            # the worker's finished signal.
            if not self.queue.is_row_active_or_waiting(row_id):
                self._set_row_status(row, "Cancelled")

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

        conc_layout = QHBoxLayout()
        conc_layout.addWidget(QLabel("Max concurrent:"))
        self.max_spinbox = QSpinBox()
        self.max_spinbox.setRange(1, 8)
        self.max_spinbox.setValue(1)
        self.max_spinbox.setToolTip("Maximum number of downloads running at once (1–8)")
        conc_layout.addWidget(self.max_spinbox)
        conc_layout.addStretch()
        options_layout.addLayout(conc_layout)

        main_layout.addWidget(options_group)

        # Progress Section (global: average of active workers)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # History Table (full width)
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["Output Name", "URL", "Status", "Progress"])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(3, 130)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setMinimumWidth(420)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(
            self.show_context_menu
        )
        self.history_table.doubleClicked.connect(self.historyDoubleClick)
        main_layout.addWidget(self.history_table, stretch=1)

        # FFmpeg log lives in a separate window, opened on demand
        self.log_dialog = LogDialog(self)

        # Controls
        control_layout = QHBoxLayout()

        self.btn_start = QPushButton("▶ Add to Queue")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.btn_start.clicked.connect(self.start_download)
        control_layout.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("⏹ Cancel All")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
        self.btn_cancel.clicked.connect(self.cancel_all)
        control_layout.addWidget(self.btn_cancel)

        self.btn_log = QPushButton("📜 Log")
        self.btn_log.setCheckable(True)
        self.btn_log.setToolTip("Show / hide the FFmpeg log window")
        self.btn_log.clicked.connect(self.toggle_log)
        control_layout.addWidget(self.btn_log)

        self.log_dialog.finished.connect(lambda _result: self.btn_log.setChecked(False))

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

    # ---- row helpers -------------------------------------------------------
    def add_history_row(self, output_name, url, status="Queued"):
        """Add a new row to the history table and return its opaque row id."""
        history_item = DownloadHistoryItem(url=url, output=output_name, status=status, progress=0)

        for i, item in enumerate(self.download_history):
            if item == history_item:
                name_item = self.history_table.item(i, 0)
                if name_item is not None:
                    return int(name_item.data(self._NumRowId))
                return -1

        row = self.history_table.rowCount()
        self.history_table.insertRow(row)

        self._row_id_seq += 1
        row_id = self._row_id_seq

        # Output Name
        name_item = QTableWidgetItem(output_name)
        name_item.setToolTip(output_name)
        name_item.setData(self._NumRowId, row_id)
        self.history_table.setItem(row, 0, name_item)

        # URL
        url_item = QTableWidgetItem(url)
        url_item.setToolTip(url)
        self.history_table.setItem(row, 1, url_item)

        # Status
        status_item = QTableWidgetItem(status)
        status_item.setToolTip(status)
        self.history_table.setItem(row, 2, status_item)

        # Per-row progress bar. Only active (Queued/Downloading) rows get one;
        # it fills the full cell height so it lines up with the row. Terminal
        # rows (e.g. loaded history) leave the cell empty instead of showing a
        # misleading empty bar next to a finished/failed entry.
        if self._is_active_status(status):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            self.history_table.setCellWidget(row, 3, bar)

        # Scroll to the new row
        self.history_table.scrollToItem(status_item)

        self.download_history.append(history_item)

        return row_id

    def _is_active_status(self, status):
        """True when the row is being worked on (bar should be visible)."""
        return status == "Queued" or status.startswith("Downloading")

    def _find_row(self, row_id):
        """Return the table row index for an opaque row id, or -1 if absent."""
        for i in range(self.history_table.rowCount()):
            item = self.history_table.item(i, 0)
            if item is not None and item.data(self._NumRowId) is not None \
                    and int(item.data(self._NumRowId)) == row_id:
                return i
        return -1

    def _bar_for(self, table_row):
        if 0 <= table_row < self.history_table.rowCount():
            return self.history_table.cellWidget(table_row, 3)
        return None

    def _set_row_status(self, table_row, text):
        """Update the status cell of a table row and its matching history item."""
        status_item = self.history_table.item(table_row, 2)
        if status_item is not None:
            status_item.setText(text)
        if 0 <= table_row < len(self.download_history):
            self.download_history[table_row].status = text

    # ---- queue signal handlers --------------------------------------------
    def _row_started(self, row_id):
        self._active_pct.pop(row_id, None)
        self._active_live.pop(row_id, None)
        r = self._find_row(row_id)
        if r >= 0:
            self._set_row_status(r, "Downloading...")
            bar = self._bar_for(r)
            if bar is None:
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setTextVisible(True)
                self.history_table.setCellWidget(r, 3, bar)
            bar.setRange(0, 100)
            bar.setValue(0)
        self._update_global_bar()

    def _row_progress(self, row_id, pct):
        self._active_live.pop(row_id, None)
        self._active_pct[row_id] = pct
        r = self._find_row(row_id)
        if r >= 0:
            self._set_row_status(r, f"Downloading... {pct}%")
            bar = self._bar_for(r)
            if bar is not None:
                bar.show()
                if bar.maximum() == 0:
                    bar.setRange(0, 100)
                bar.setValue(pct)
        self._update_global_bar()

    def _row_live(self, row_id, duration_known):
        if duration_known:
            self._active_live.pop(row_id, None)
        else:
            self._active_live[row_id] = True
            self._active_pct.pop(row_id, None)
        r = self._find_row(row_id)
        if r >= 0:
            bar = self._bar_for(r)
            if bar is not None:
                if duration_known:
                    bar.setRange(0, 100)
                    bar.setValue(0)
                else:
                    bar.setRange(0, 0)  # indeterminate (live stream)
        self._update_global_bar()

    def _row_finished(self, row_id, success, message):
        self._active_pct.pop(row_id, None)
        self._active_live.pop(row_id, None)
        lines = (message or "").splitlines()
        first_line = lines[0] if lines else ""
        cancelled = "cancel" in (message or "").lower()

        r = self._find_row(row_id)
        if r >= 0:
            if success:
                self._set_row_status(r, "Downloaded")
            elif cancelled:
                self._set_row_status(r, "Cancelled")
            else:
                self._set_row_status(r, f"Failed: {first_line[:50]}")
            # Terminal state: remove the per-row bar so finished rows leave an
            # empty Progress cell (hide() on a cell widget doesn't stick, but
            # clearing the cell widget does).
            if self._bar_for(r) is not None:
                self.history_table.setCellWidget(r, 3, None)

        if not success and not cancelled:
            QMessageBox.warning(self, "Download Status", message)
        elif not success and cancelled:
            self.status_bar.showMessage("Cancelled")

        self.save_history()
        self._update_global_bar()
        self._update_state()

    # ---- global bar / state -----------------------------------------------
    def _update_global_bar(self):
        active_ids = set(self._active_pct) | set(self._active_live)
        pcts = [self._active_pct[rid] for rid in active_ids if rid in self._active_pct]
        if not active_ids:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
        elif not pcts:
            # Every active worker is a live stream with no known duration.
            self.progress_bar.setRange(0, 0)
        else:
            avg = round(sum(pcts) / len(pcts))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(avg)

    def _update_state(self):
        active = self.queue.active_count()
        waiting = self.queue.waiting_count()
        self.btn_cancel.setEnabled(active > 0 or waiting > 0)
        if active > 0 and waiting > 0:
            self.status_bar.showMessage(f"Active: {active} | Waiting: {waiting}")
        elif waiting > 0:
            self.status_bar.showMessage(f"Waiting: {waiting}")

    # ---- actions -----------------------------------------------------------
    def start_download(self):
        try:
            url = self.url_input.currentText().strip()
            output = self.output_input.currentText().strip() or "output.mp4"
            # Only force .mp4 when no known media extension is present, so that
            # e.g. ".mkv" (useful for HLS streams with AC-3 audio) is respected.
            if not re.search(r'\.(mp4|mkv|mov|m4v|webm|ts|avi)$', output, re.IGNORECASE):
                output += ".mp4"

            if not url:
                raise ValueError("Please enter a valid M3U8 URL")

            # Validate the command up front so bad extra args surface immediately
            # (the queue would otherwise report it as a failed row).
            self.build_cmd(url, output)

            if not self.confirm_overwrite(output):
                return

            self.addUrl(url)
            self.addOut(output)
            self.saveSettings()

            output_name = os.path.basename(output)
            row_id = self.add_history_row(output_name, url, "Queued")
            self.append_log(
                f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            self.queue.enqueue(row_id, url, output)

        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

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

    def cancel_all(self):
        if not self.queue.is_running() and self.queue.waiting_count() == 0:
            return
        # Waiting rows are dropped without a finished signal; reflect it now.
        for rid in self.queue.waiting_row_ids():
            r = self._find_row(rid)
            if r >= 0:
                self._set_row_status(r, "Cancelled")
        self.queue.cancel_all()
        self.status_bar.showMessage("Cancelling...")

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

    def append_log(self, text):
        # Write to the log window whether or not it is currently visible.
        self.log_dialog.append(text)

    def toggle_log(self, checked):
        if checked:
            self.log_dialog.show()
            self.log_dialog.raise_()
            self.log_dialog.activateWindow()
        else:
            self.log_dialog.hide()

    def clear_history(self):
        """Clear all rows from the history table."""
        self.history_table.setRowCount(0)
        self.download_history = []
        self._active_pct.clear()
        self._active_live.clear()


if __name__ == '__main__':
    app = QApplication(sys.argv)

    app.setOrganizationName("VideoTools")
    app.setApplicationName("MP4 Downloader")

    icon_path = pick_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

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
    if icon_path:
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec())
