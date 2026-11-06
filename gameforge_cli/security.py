"""
Безопасное хранение конфигурации Gameforge CLI.

Все чувствительные данные (токены, пароли) шифруются с помощью
Fernet (AES-128 в режиме CBC с HMAC для проверки целостности).
Ключ шифрования хранится в ~/.gameforge-cli/.key с правами доступа 0o600.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

CONFIG_DIR = Path.home() / ".gameforge-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEY_FILE = CONFIG_DIR / ".key"
HISTORY_FILE = CONFIG_DIR / "history.json"


def _get_or_create_key() -> bytes:
    """Создает или загружает ключ шифрования.

    Ключ хранится в ~/.gameforge-cli/.key с правами доступа только для владельца (0o600).
    """
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    os.chmod(KEY_FILE, 0o600)
    return key


def _encrypt(value: str) -> str:
    """Шифрует строку с помощью Fernet (AES-128 + HMAC)."""
    f = Fernet(_get_or_create_key())
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str) -> str:
    """Расшифровывает строку, зашифрованную с помощью Fernet."""
    f = Fernet(_get_or_create_key())
    return f.decrypt(value.encode("utf-8")).decode("utf-8")


def load_config() -> dict[str, Any]:
    """Загружает конфигурацию из файла с расшифровкой чувствительных полей.

    Если файл не существует или поврежден, возвращает пустой словарь.
    Токен расшифровывается при загрузке.
    """
    if not CONFIG_FILE.exists():
        return {}

    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return {}

    # Расшифровываем токены, если они зашифрованы
    for key in ("token", "runner_token"):
        if data.get(key):
            try:
                data[key] = _decrypt(data[key])
            except Exception:  # noqa: BLE001
                data[key] = None

    return data


def save_config(config: dict[str, Any]) -> None:
    """Сохраняет конфигурацию с шифрованием чувствительных полей.

    Токен шифруется перед записью на диск. Права доступа к файлу
    устанавливаются в 0o600 (только владелец).
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    encrypted = config.copy()
    if encrypted.get("token"):
        encrypted["token"] = _encrypt(encrypted["token"])
    if encrypted.get("runner_token"):
        encrypted["runner_token"] = _encrypt(encrypted["runner_token"])

    CONFIG_FILE.write_text(json.dumps(encrypted, indent=2), encoding="utf-8")
    os.chmod(CONFIG_FILE, 0o600)


def clear_config() -> None:
    """Полностью удаляет конфигурацию и ключ шифрования."""
    CONFIG_FILE.unlink(missing_ok=True)
    KEY_FILE.unlink(missing_ok=True)
    HISTORY_FILE.unlink(missing_ok=True)


def is_configured() -> bool:
    """Проверяет, настроен ли клиент (есть ли токен и базовый URL)."""
    config = load_config()
    return bool(config.get("token") and config.get("base_url"))


def get_secure_config() -> dict[str, Any]:
    """Возвращает конфигурацию с расшифрованным токеном."""
    return load_config()


def mask_token(token: str | None) -> str:
    """Маскирует токен для отображения в логах и интерфейсе."""
    if not token:
        return "не настроен"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"


def is_secure_connection(url: str) -> bool:
    """Проверяет, использует ли URL безопасное соединение (HTTPS)."""
    return url.startswith(("https://", "http://localhost", "http://127.0.0.1"))


def warn_insecure_url(url: str) -> None:
    """Выводит предупреждение, если используется небезопасное соединение."""
    if not is_secure_connection(url):
        print(
            "⚠️  ПРЕДУПРЕЖДЕНИЕ: Соединение не зашифровано (HTTP вместо HTTPS). "
            "Токен может быть перехвачен. Используйте HTTPS для продакшена."
        )