#!/usr/bin/env bash
# Builds a single-file program for this platform with PyInstaller.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python=${PYTHON:-python3}
if ! "$python" -c 'import tkinter' 2>/dev/null; then
  echo "This Python has no Tk. Install the Tk package of your system, such as python3-tk or tk." >&2
  exit 1
fi
if [[ ! -x build/venv/bin/python ]]; then
  "$python" -m venv build/venv
fi
build/venv/bin/python -m pip install --disable-pip-version-check pyinstaller==6.22.3
build/venv/bin/python -m PyInstaller --onefile --windowed --noconfirm --name wt-sound-volume \
  --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller app.py
