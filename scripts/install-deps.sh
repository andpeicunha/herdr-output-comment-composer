#!/usr/bin/env sh
# Install Python dependencies for output-comment-composer
# Exits 0 even if pip is unavailable — the plugin binary handles the missing dep gracefully.

if python3 -c "import textual" 2>/dev/null; then
  echo "textual already installed"
  exit 0
fi

_pip_install() {
  "$@" install textual && exit 0
  "$@" install textual --break-system-packages && exit 0
}

if command -v pip3 >/dev/null 2>&1; then _pip_install pip3; fi
if command -v pip >/dev/null 2>&1; then _pip_install pip; fi
if python3 -m pip --version >/dev/null 2>&1; then _pip_install python3 -m pip; fi

echo "output-comment-composer: could not install textual automatically." >&2
echo "Install manually:" >&2
echo "  pip3 install textual --break-system-packages" >&2
echo "  or: pipx install textual" >&2
exit 0
