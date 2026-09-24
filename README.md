## Downloading m3u8 to a mp4 container

###  build stand-alone app

Requires the MSVC x64 environment (`cl.exe` in PATH), otherwise Nuitka fails
with "cannot locate suitable C compiler":

```bat
call "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
```

```bat
:: put the stand-alone ffmpeg.exe into the project directory
pip install nuitka pyside6
python -m nuitka --standalone --onefile ^
  --enable-plugin=pyside6 ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=assets/icon.ico ^
  --include-data-files=ffmpeg.exe=ffmpeg.exe ^
  --include-data-dir=assets=assets ^
  --include-windows-runtime-dlls=yes ^
  --assume-yes-for-downloads ^
  --output-dir=build video-downloader.py
```

Notes:

- `--windows-icon-from-ico` associates the app icon with the .exe itself
  (Explorer/taskbar), in addition to the runtime window icon.
- `--include-data-dir=assets=assets` bundles the icon files into the onefile
  (a directory must use `--include-data-dir`, not `--include-data-files`).
- `--assume-yes-for-downloads` avoids the interactive download prompt.
- The local modules (`models.py`, `widgets.py`, `download_queue.py`,
  `ffmpeg_worker.py`, `filehistorycombo.py`) are picked up automatically by
  Nuitka's import scan — no extra flags needed.
- `video-downloader.py` is the canonical entry point; `video-downloader2.py` /
  `3.py` are experiments.

Smoke test the built EXE (onefile extraction of ~80 MB takes a while):

```bash
cd build
QT_QPA_PLATFORM=offscreen ./video-downloader.exe &
PID=$!; sleep 50
kill -0 $PID && echo "OK: running" || wait $PID
taskkill //F //PID $PID //T
```
