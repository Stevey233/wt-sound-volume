#!/usr/bin/env bash
# Builds the Windows x86-64 program on Linux. PyInstaller can't cross-compile,
# so it runs inside Windows Python under Wine. The release build runs on a
# Windows runner instead, see .github/workflows/ci.yml.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
repo_dir=$PWD
build_dir="$repo_dir/build/windows"
python_dir="$build_dir/python313"
mkdir -p "$build_dir/download"
# winemenubuilder would add file associations for this prefix to the desktop.
export WINEPREFIX="$build_dir/prefix" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d"
# No display, so Wine can't open windows on the desktop.
wine_python() {
  env -u DISPLAY -u WAYLAND_DISPLAY wine "$python_dir/python.exe" "$@"
}
if [[ ! -f "$python_dir/python.exe" ]]; then
  python3 - "$build_dir/download" <<'PY'
import hashlib
from pathlib import Path
import sys
import urllib.request

directory = Path(sys.argv[1])
package = directory / "python-3.13.17-amd64.zip"
url = "https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.zip"
expected = "b26ca4b4ee51e157836049934d2b8eabd55939be296f3130254251b6df96ec2f"
if not package.exists():
    urllib.request.urlretrieve(url, package)
if hashlib.sha256(package.read_bytes()).hexdigest() != expected:
    raise SystemExit("Windows Python package SHA-256 mismatch")
PY
  rm -rf "$python_dir.partial"
  python3 -m zipfile -e "$build_dir/download/python-3.13.17-amd64.zip" "$python_dir.partial"
  mv "$python_dir.partial" "$python_dir"
fi
if ! wine_python -c "import PyInstaller, sys; sys.exit(PyInstaller.__version__ != '6.22.3')" 2>/dev/null; then
  wine_python -m pip install --disable-pip-version-check pyinstaller==6.22.3
fi
winpath() {
  env -u DISPLAY -u WAYLAND_DISPLAY winepath -w "$1" 2>/dev/null
}
wine_python -m PyInstaller --onefile --windowed --noconfirm --name wt-sound-volume \
  --distpath "$(winpath "$repo_dir/dist/windows")" --workpath "$(winpath "$build_dir/pyinstaller")" \
  --specpath "$(winpath "$build_dir/pyinstaller")" "$(winpath "$repo_dir/app.py")"
cp "$python_dir/LICENSE.txt" "$repo_dir/dist/windows/python-license.txt"
cp "$python_dir/tcl/tk8.6/license.terms" "$repo_dir/dist/windows/tk-license.txt"
