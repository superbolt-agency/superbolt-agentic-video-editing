#!/bin/bash
# Usage: setup.sh <workdir>   — creates venv (ffmpeg, whisper, PIL), folders and fonts in the workdir.
set -e
W="${1:-.}"; mkdir -p "$W"; cd "$W"
# mlx-whisper needs torch, which lags new Python releases (none for 3.15 yet), so don't trust plain python3.
PY=""
for v in 3.13 3.12 3.14 3.11 3.10; do
  for p in "/opt/homebrew/bin/python$v" "$(command -v python$v 2>/dev/null)"; do
    [ -n "$p" ] && [ -x "$p" ] && { PY="$p"; break 2; }
  done
done
if [ -z "$PY" ]; then
  echo "No compatible Python (3.10-3.14) found. Install one with: brew install python@3.13" >&2; exit 1
fi
if [ -d venv ] && ! ./venv/bin/python -c 'import sys; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,14)))' 2>/dev/null; then
  echo "Existing venv uses an incompatible Python; rebuilding it."; rm -rf venv
fi
[ -d venv ] || "$PY" -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q imageio-ffmpeg mlx-whisper pillow numpy
FF=$(./venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
ln -sf "$FF" venv/bin/ffmpeg
mkdir -p raw proxy audio tx sheets qa parts fonts
for d in "$HOME/Library/Fonts" /Library/Fonts; do
  cp "$d"/Montserrat-Black.otf "$d"/Montserrat-ExtraBold.otf fonts/ 2>/dev/null || true
done
[ -n "$(ls fonts)" ] || cp "/System/Library/Fonts/Supplemental/Arial Black.ttf" fonts/
echo "python: $(./venv/bin/python --version)"
./venv/bin/ffmpeg -version | head -1
echo "fonts: $(ls fonts | tr '\n' ' ')"
