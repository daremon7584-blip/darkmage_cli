#!/usr/bin/env python3
# =============================================================================
# Darkmage AI CLI — установщик для Windows и как кроссплатформенный fallback
# =============================================================================
# Использование:
#   python install.py <IP_СЕРВЕРА>
#   или: python install.py --server 148.135.203.133
#
# Безопасность: команды запускаются списком argv (без shell=True), а адрес
# сервера проверяется до подстановки в URL и строки конфига.
# =============================================================================

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
import urllib.request
import urllib.error

REPO_URL = "https://github.com/daremon7584-blip/arkost_cli.git"
REPO_DIRNAME = "arkost_cli"

# Only a DNS name, IPv4 address, or `localhost` is accepted. This prevents
# injecting shell/rc syntax or URL components through the server argument.
_SERVER_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$"
)


def validate_server(server: str) -> str:
    """Validate the server host before it is used in URLs or shell rc lines."""
    server = server.strip()
    if (
        not server
        or len(server) > 253
        or ".." in server
        or server[0] in ".-"
        or server[-1] in ".-"
        or not _SERVER_RE.fullmatch(server)
    ):
        raise ValueError(
            "Некорректный адрес сервера. Укажите только домен или IP "
            "(буквы, цифры, точки и дефис), например 148.135.203.133"
        )
    return server


def run(argv: list[str], cwd: Path | None = None) -> None:
    """Run a command as an argv list (never through a shell)."""
    argv = [str(part) for part in argv]
    print(f"▶ {shlex.join(argv)}")
    result = subprocess.run(argv, cwd=cwd, check=False)
    if result.returncode != 0:
        print(f"❌ Команда не удалась: {shlex.join(argv)}")
        sys.exit(result.returncode)


def detect_python() -> str:
    """Возвращает команду для запуска Python."""
    for name in ("python3", "python", "py"):
        try:
            subprocess.run([name, "--version"], capture_output=True, check=True)
            return name
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    print("❌ Python 3.10+ не найден. Установите с https://python.org")
    sys.exit(1)


def install_python_deps(python_cmd: str) -> None:
    """Устанавливает Python зависимости."""
    print("▶ Установка Python зависимостей...")
    run(
        [
            python_cmd,
            "-m",
            "pip",
            "install",
            "httpx",
            "textual",
            "websockets",
            "pydantic-settings",
            "cryptography",
        ]
    )

    # cryptography нужен для шифрования токена в конфиге.
    # В Termux с Python 3.14 пред собранное wheel может не совпадать с ABI
    # (символ PyBaseObject_Type отсутствует). Пробуем обычное установление,
    # а если не сработает — пересобираем из исходников.
    try:
        subprocess.run(
            [python_cmd, "-c", "from cryptography.fernet import Fernet"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        print("▶ Пересборка cryptography из исходников (для совместимости с Python)...")
        run(
            [
                python_cmd,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-binary",
                ":all:",
                "cryptography",
            ]
        )


def _origin_matches(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    return result.stdout.strip().rstrip("/") == REPO_URL.rstrip("/")


def clone_repo() -> Path:
    """Клонирует или обновляет репозиторий, не удаляя пользовательские файлы."""
    repo_dir = Path.home() / REPO_DIRNAME
    if repo_dir.exists():
        if not (repo_dir / ".git").is_dir() or not _origin_matches(repo_dir):
            print(
                f"❌ {repo_dir} уже существует, но это не клон {REPO_URL}.\n"
                "   Переместите или удалите его вручную и запустите установку снова."
            )
            sys.exit(2)
        print("▶ Обновление существующего клона arkost_cli (git pull --ff-only)...")
        run(["git", "-C", str(repo_dir), "pull", "--ff-only"])
        return repo_dir

    print("▶ Клонирование arkost_cli...")
    run(["git", "clone", REPO_URL, str(repo_dir)])
    return repo_dir


def install_cli(python_cmd: str, repo_dir: Path) -> None:
    """Устанавливает CLI как команду."""
    print("▶ Установка команды darkmage...")
    run([python_cmd, "-m", "pip", "install", "-e", "."], cwd=repo_dir)


def write_config(server: str) -> None:
    """Добавляет переменные окружения в файл профиля оболочки."""
    home = Path.home()
    # Определяем файл профиля
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        rc_file = home / ".zshrc"
    else:
        rc_file = home / ".bashrc"

    marker = "# Darkmage AI CLI configuration"
    if rc_file.exists() and marker in rc_file.read_text(encoding="utf-8"):
        print(f"▶ Конфиг уже есть в {rc_file}, пропускаем")
        return

    lines = [
        "",
        marker,
        f'export DARKMAGE_API_URL="http://{server}:8000"',
        'export DARKMAGE_TOKEN=""',
        f'export DARKMAGE_RUNNER_URL="http://{server}:8090"',
        'export DARKMAGE_RUNNER_TOKEN=""',
        "",
    ]
    with open(rc_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"▶ Настройки добавлены в {rc_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Установка Darkmage AI CLI")
    parser.add_argument("server", nargs="?", help="IP или домен сервера Darkmage AI")
    parser.add_argument("--server", dest="server_flag", help="IP или домен сервера")
    args = parser.parse_args()

    server = args.server or args.server_flag
    if not server:
        server = os.environ.get("DARKMAGE_SERVER", "")
    if not server:
        print("╔════════════════════════════════════════════════════════════════════╗")
        print("║  🧙‍♂️  Darkmage AI CLI — установка                                ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        print("")
        print("⚠️  Укажите IP или домен сервера:")
        print("   python install.py <IP_СЕРВЕРА>")
        print("   Пример: python install.py 148.135.203.133")
        print("")
        sys.exit(1)

    try:
        server = validate_server(server)
    except ValueError as exc:
        print(f"❌ {exc}")
        sys.exit(2)

    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  🧙‍♂️  Darkmage AI CLI — установка                                ║")
    print(f"║  Сервер: {server:<58}║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    # Health-check сервера
    print("▶ Проверка сервера", server, ":8000...")
    try:
        req = urllib.request.Request(f"http://{server}:8000/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print("   ✅ Сервер отвечает")
            else:
                print(f"   ⚠️  Сервер вернул статус {resp.status}")
                print("      Установка продолжится, но проверьте, что сервер запущен.")
    except urllib.error.URLError as e:
        print(f"   ⚠️  Сервер не отвечает: {e}")
        print("      Установка продолжится, но проверьте, что сервер запущен.")
    except Exception as e:
        print(f"   ⚠️  Не удалось проверить сервер: {e}")
        print("      Установка продолжится.")
    print()

    python_cmd = detect_python()
    install_python_deps(python_cmd)
    repo_dir = clone_repo()
    install_cli(python_cmd, repo_dir)
    write_config(server)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  ✅ Установка завершена!                                            ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print("📋 Следующие шаги:")
    print()
    print("  1. Первый вход (создаст аккаунт или войдёт в существующий):")
    print("     darkmage auth interactive")
    print()
    print("  2. Посмотреть рабочие зоны:")
    print("     darkmage workspace list")
    print()
    print("  3. Запустить TUI для рабочей зоны:")
    print("     darkmage tui <workspace_id>")
    print()
    print(f"🌐 Сервер API: http://{server}:8000")
    print()
    print("💡 Если команда 'darkmage' не найдена — перезапустите терминал или")
    print("   добавьте ~/.local/bin в PATH")


if __name__ == "__main__":
    main()
