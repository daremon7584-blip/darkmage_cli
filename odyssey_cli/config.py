from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".odyssey-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_BASE_URL = "http://localhost:8000"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_base_url() -> str:
    return os.environ.get("ODYSSEY_API_URL") or load_config().get(
        "base_url", DEFAULT_BASE_URL
    ).rstrip("/")


def set_base_url(url: str) -> None:
    config = load_config()
    config["base_url"] = url.rstrip("/")
    save_config(config)


def get_token() -> str | None:
    return os.environ.get("ODYSSEY_TOKEN") or load_config().get("token")


def set_token(token: str | None) -> None:
    config = load_config()
    if token is None:
        config.pop("token", None)
    else:
        config["token"] = token
    save_config(config)
