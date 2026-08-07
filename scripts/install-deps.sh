#!/usr/bin/env sh
# Install Python dependencies for output-comment-composer
set -e

if python3 -c "import textual" 2>/dev/null; then
  echo "textual already installed"
  exit 0
fi

if command -v pip3 >/dev/null 2>&1; then
  pip3 install textual
elif command -v pip >/dev/null 2>&1; then
  pip install textual
elif python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install textual
else
  echo "WARNING: pip not found. Install textual manually: python3 -m pip install textual" >&2
  exit 1
fi
