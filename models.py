"""Data model + non-GUI helpers shared by the downloader.

Kept free of any QWidget so it can be imported and tested without a Qt app.
"""
import shutil
import sys
from pathlib import Path
from datetime import datetime


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
