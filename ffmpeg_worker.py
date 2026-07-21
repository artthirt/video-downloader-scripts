import subprocess
import re
import sys
from PySide6.QtCore import Signal, QThread

class FFmpegWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    log = Signal(str)
    finished = Signal(bool, str)
    
    def __init__(self, cmd_args, id, parent=None):
        super().__init__(parent)
        self.cmd_args = cmd_args
        self.process = None
        self._is_running = True
        self.duration_seconds = 0
        self.duration_found = False
        self.id = id

    def is_running(self):
        return self._is_running
        
    def time_to_seconds(self, time_str):
        try:
            parts = time_str.split(':')
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        except:
            return 0
    
    def stop(self):
        self._is_running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                self.process.kill()
    
    def parse_line(self, line):
        """Parse a single line of FFmpeg output"""
        # Log the line
        self.log.emit(line + '\n')
        
        # Parse duration (only once)
        if not self.duration_found:
            duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})', line)
            if duration_match:
                time_str = f"{duration_match.group(1)}:{duration_match.group(2)}:{duration_match.group(3)}"
                self.duration_seconds = self.time_to_seconds(time_str)
                self.duration_found = True
                self.status.emit(f"Duration: {time_str} ({int(self.duration_seconds)}s)")
        
        # Parse progress
        if self.duration_seconds > 0:
            time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2}\.\d{2})', line)
            if time_match:
                current_time_str = f"{time_match.group(1)}:{time_match.group(2)}:{time_match.group(3)}"
                current_seconds = self.time_to_seconds(current_time_str)
                percent = min(int((current_seconds / self.duration_seconds) * 100), 99)
                self.progress.emit(percent)
                self.status.emit(f"Downloading: {percent}% ({current_time_str})")
        else:
            # For live streams, show frame count or size
            frame_match = re.search(r'frame=\s*(\d+)', line)
            size_match = re.search(r'size=\s*(\d+)kB', line)
            fps_match = re.search(r'fps=\s*(\d+)', line)
            if frame_match or size_match:
                info = []
                if frame_match:
                    info.append(f"Frame {frame_match.group(1)}")
                if fps_match:
                    info.append(f"{fps_match.group(1)}fps")
                if size_match:
                    info.append(f"{int(size_match.group(1))/1024:.1f}MB")
                self.status.emit(f"Downloading... {' | '.join(info)}")
    
    def run(self):
        self.status.emit("Starting FFmpeg...")
        
        try:
            # CRITICAL FIX: Use subprocess with unbuffered output
            # -stderr=subprocess.STDOUT merges stderr into stdout
            # -bufsize=1 enables line buffering
            # -universal_newlines=True for text mode
            
            cmd = ['ffmpeg'] + self.cmd_args
            
            self.log.emit(f"Executing: {' '.join(cmd)}\n")
            self.log.emit("-" * 50 + "\n")
            
            # Use CREATE_NO_WINDOW on Windows to prevent console popup
            creationflags = 0
            if sys.platform == 'win32':
                creationflags = subprocess.CREATE_NO_WINDOW
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags
            )
            
            # Read output line by line
            for line in self.process.stdout:
                if not self._is_running:
                    self.process.terminate()
                    self.finished.emit(False, "Download cancelled by user")
                    return
                
                line = line.rstrip()
                if line:
                    self.parse_line(line)
            
            # Wait for process to complete
            self.process.wait()
            
            if self.process.returncode == 0:
                self.progress.emit(100)
                self.finished.emit(True, "Download completed successfully!")
            else:
                self.finished.emit(False, f"FFmpeg exited with code {self.process.returncode}")
                
        except Exception as e:
            self._is_running = False
            self.finished.emit(False, f"Error: {str(e)}")