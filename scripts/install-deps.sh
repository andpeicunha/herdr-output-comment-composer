#!/usr/bin/env sh
# Install Python dependencies for output-comment-composer
# Exits 0 even if pip is unavailable — the plugin binary handles the missing dep gracefully.

if python3 -c "import textual" 2>/dev/null; then
  echo "textual already installed"
  exit 0
fi

if command -v pip3 >/dev/null 2>&1; then
  pip3 install textual && exit 0
fi

if command -v pip >/dev/null 2>&1; then
  pip install textual && exit 0
fi

if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install textual && exit 0
fi

echo "output-comment-composer: pip not found — install textual manually:" >&2
echo "  python3 -m pip install textual" >&2
echo "  or: sudo apt install python3-pip && pip3 install textual" >&2
exit 0
