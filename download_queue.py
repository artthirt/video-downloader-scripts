"""Concurrency engine: run N ffmpeg downloads with a FIFO waiting list.

This module owns scheduling and the worker lifecycle, and is deliberately
decoupled from the GUI. It emits row-id-keyed signals so the window can update
whichever table row / progress bar matches. The row id is an opaque key chosen
by the caller (the UI uses the history-table row index at insert time).
"""
from PySide6.QtCore import QObject, Signal

from ffmpeg_worker import FFmpegWorker


class DownloadQueue(QObject):
    started = Signal(int)                 # row_id
    progress = Signal(int, int)           # row_id, percent (0..99)
    live = Signal(int, bool)              # row_id, duration_known
    finished = Signal(int, bool, str)     # row_id, success, message
    log = Signal(str)
    state_changed = Signal()              # active / waiting counts changed

    def __init__(self, ffmpeg_path, build_cmd, parent=None):
        super().__init__(parent)
        self.ffmpeg_path = ffmpeg_path
        self._build_cmd = build_cmd  # callable(url, output) -> list[str]
        self._max = 1
        self._active = {}     # row_id -> FFmpegWorker
        self._waiting = []    # list of (row_id, url, output)

    # ---- configuration ----
    def max_concurrent(self):
        return self._max

    def set_max_concurrent(self, n):
        n = max(1, int(n))
        if n != self._max:
            self._max = n
            self.pump()
            self.state_changed.emit()

    # ---- state ----
    def active_count(self):
        return len(self._active)

    def waiting_count(self):
        return len(self._waiting)

    def is_running(self):
        return bool(self._active)

    def active_row_ids(self):
        return list(self._active)

    def waiting_row_ids(self):
        return [t[0] for t in self._waiting]

    def is_row_active_or_waiting(self, row_id):
        return row_id in self._active or row_id in self.waiting_row_ids()

    # ---- enqueue / dispatch ----
    def enqueue(self, row_id, url, output):
        self._waiting.append((row_id, url, output))
        self.state_changed.emit()
        self.pump()

    def pump(self):
        """Start as many waiting downloads as the concurrency cap allows."""
        while len(self._active) < self._max and self._waiting:
            row_id, url, output = self._waiting.pop(0)
            self._launch(row_id, url, output)

    def _launch(self, row_id, url, output):
        try:
            cmd = self._build_cmd(url, output)
        except ValueError as e:
            # Bad input: report as a failed row and keep pumping.
            self.finished.emit(row_id, False, str(e))
            self.state_changed.emit()
            return

        worker = FFmpegWorker(cmd, id=row_id, ffmpeg_path=self.ffmpeg_path)
        worker.progress.connect(self._on_progress)
        worker.duration_found.connect(self._on_live)
        worker.log.connect(self.log.emit)
        worker.finished.connect(self._on_finished)

        self._active[row_id] = worker
        self.started.emit(row_id)
        self.state_changed.emit()
        worker.start()

    # ---- per-worker slots (disambiguated via QObject.sender()) ----
    def _on_progress(self, pct):
        self.progress.emit(self.sender().id, pct)

    def _on_live(self, duration_known):
        self.live.emit(self.sender().id, duration_known)

    def _on_finished(self, success, message):
        worker = self.sender()
        row_id = worker.id
        self._active.pop(row_id, None)
        # The thread has essentially ended (finished is the last emit in run());
        # wait() is a cheap safety net before we drop our reference to it.
        worker.wait(2000)
        self.finished.emit(row_id, success, message)
        self.state_changed.emit()
        self.pump()

    # ---- cancellation ----
    def cancel_row(self, row_id):
        worker = self._active.get(row_id)
        if worker is not None:
            worker.stop()
        else:
            self._waiting = [t for t in self._waiting if t[0] != row_id]
        self.state_changed.emit()

    def cancel_all(self):
        for worker in list(self._active.values()):
            worker.stop()
        self._waiting.clear()
        self.state_changed.emit()

    def stop_all(self):
        """Block until every active worker exits (used by closeEvent)."""
        for worker in list(self._active.values()):
            worker.stop()
        for worker in list(self._active.values()):
            worker.wait(10000)
