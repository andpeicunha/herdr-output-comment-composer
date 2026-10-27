"""User settings: environment variables first, then ``config.env`` in the plugin config dir."""
from __future__ import annotations

import os

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
