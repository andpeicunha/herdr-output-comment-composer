"""User settings: environment variables first, then ``config.env`` in the plugin config dir."""
from __future__ import annotations

import os
import tempfile

from herdr_shared_ui.themes import DEFAULT_THEME, THEME_IDS, normalize_theme

CONFIG_FILE_NAME = "config.env"


def parse_config_env(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines; ignore blanks and # comments; strip matching quotes."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def config_file_values() -> dict[str, str]:
    """Read ``$HERDR_PLUGIN_CONFIG_DIR/config.env``; empty when missing or unreadable."""
    config_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR", "")
    if not config_dir:
        return {}
    try:
        with open(os.path.join(config_dir, CONFIG_FILE_NAME), encoding="utf-8") as source:
            return parse_config_env(source.read())
    except OSError:
        return {}


def setting(name: str, default: str = "") -> str:
    """Return a setting; an environment variable wins over the config file."""
    if name in os.environ:
        return os.environ[name]
    return config_file_values().get(name, default)


def selected_theme() -> str:
    """Read the Composer theme with the shared styled default."""
    return normalize_theme(setting("OCC_THEME", DEFAULT_THEME).strip())


def save_theme(theme: str) -> bool:
    """Persist a supported theme without dropping unrelated plugin settings."""
    theme = normalize_theme(theme)
    config_dir = os.environ.get("HERDR_PLUGIN_CONFIG_DIR", "")
    if not config_dir:
        return False
    path = os.path.join(config_dir, CONFIG_FILE_NAME)
    try:
        try:
            with open(path, encoding="utf-8") as source:
                lines = source.read().splitlines()
        except FileNotFoundError:
            lines = []
        output = []
        replaced = False
        for line in lines:
            key, separator, _value = line.partition("=")
            if separator and key.strip() == "OCC_THEME":
                if not replaced:
                    output.append(f"OCC_THEME={theme}")
                    replaced = True
            else:
                output.append(line)
        if not replaced:
            output.append(f"OCC_THEME={theme}")
        os.makedirs(config_dir, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".config.env.", dir=config_dir, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                target.write("\n".join(output) + "\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return True
    except OSError:
        return False


def next_theme(theme: str) -> str:
    """Return the next shared theme in the documented cycle."""
    current = normalize_theme(theme)
    return THEME_IDS[(THEME_IDS.index(current) + 1) % len(THEME_IDS)]
