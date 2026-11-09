"""
Безопасное хранение конфигурации Darkmage CLI.

Все чувствительные данные (токены, пароли) шифруются с помощью
Fernet (AES-128 в режиме CBC с HMAC для проверки целостности).
Ключ шифрования хранится в ~/.darkmage-cli/.key с правами доступа 0o600.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

from cryptography.fernet import Fernet

CONFIG_DIR = Path.home() / ".darkmage-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
KEY_FILE = CONFIG_DIR / ".key"
HISTORY_FILE = CONFIG_DIR / "history.json"

# Placeholder written by `config export` instead of a decrypted secret.
REDACTED = "***REDACTED***"

_SECRET_KEY_MARKERS = (
    "token",
    "password",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
)


def is_secret_key(key: str) -> bool:
    """Return True when a config key holds a credential."""
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in _SECRET_KEY_MARKERS)


def is_redacted_value(value: Any) -> bool:
    return isinstance(value, str) and value == REDACTED


def _redact_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if is_secret_key(str(key)) and item else _redact_nested(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_nested(item) for item in value]
    return value


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *config* with all credential values replaced.

    The token is never copied into CLI output, logs, or exported files.
    """
    return {
        key: REDACTED if is_secret_key(str(key)) and value else _redact_nested(value)
        for key, value in config.items()
    }


def strip_redacted(config: dict[str, Any]) -> dict[str, Any]:
    """Drop redacted placeholders so importing an export cannot erase secrets."""
    return {
        key: value
        for key, value in config.items()
        if not (is_secret_key(str(key)) and is_redacted_value(value))
    }


def _write_private(path: str | Path, write: Any) -> None:
    target = Path(path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def write_private_json(path: str | Path, data: Any) -> None:
    """Atomically write JSON with owner-only (0600) permissions."""
    _write_private(
        path,
        lambda handle: json.dump(data, handle, ensure_ascii=False, indent=2),
    )


def write_private_text(path: str | Path, text: str) -> None:
    """Atomically write text with owner-only (0600) permissions."""
    _write_private(path, lambda handle: handle.write(text))


def _get_or_create_key() -> bytes:
    """Создает или загружает ключ шифрования.

    Ключ хранится в ~/.darkmage-cli/.key с правами доступа только для владельца (0o600).
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
    """Backward-compatible alias for :func:`darkmage_cli.config.is_configured`.

    Keeping a single implementation avoids the old split semantics where
    ``security`` ignored environment tokens and the default base URL.
    """
    from .config import is_configured as _is_configured

    return _is_configured()


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
    """Проверяет, использует ли URL безопасное соединение (HTTPS).

    Loopback hosts are treated as safe for local development. Compare the
    parsed hostname instead of using ``startswith`` so a URL such as
    ``http://localhost.evil.example`` is still reported as insecure.
    """
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(
        ".localhost"
    )


def warn_insecure_url(url: str, *, file: TextIO | None = None) -> None:
    """Выводит предупреждение, если используется небезопасное соединение.

    Warnings go to stderr by default so JSON/one-shot stdout stays machine
    readable. The function is advisory and never changes command behaviour.
    """
    if not is_secure_connection(url):
        print(
            "⚠️  ПРЕДУПРЕЖДЕНИЕ: Соединение не зашифровано (HTTP вместо HTTPS). "
            "Токен может быть перехвачен. Используйте HTTPS для продакшена.",
            file=file or sys.stderr,
        )
