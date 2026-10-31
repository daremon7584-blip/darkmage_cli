from __future__ import annotations

import os

from .security import (
    CONFIG_DIR,  # noqa: F401
    CONFIG_FILE,  # noqa: F401
    load_config,
    save_config,
)

DEFAULT_BASE_URL = "http://localhost:8000"


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


def is_configured() -> bool:
    return load_config().get("token") is not None and bool(get_base_url())


def clear_config() -> None:
    from .security import clear_config as _clear_config

    _clear_config()


def mask_token(token: str | None) -> str:
    if not token:
        return "не настроен"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"