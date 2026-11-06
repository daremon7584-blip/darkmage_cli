#!/usr/bin/env python3
# =============================================================================
# Darkmage AI CLI — установщик для Windows и как кроссплатформенный fallback
# =============================================================================
# Использование:
#   python install.py <IP_СЕРВЕРА>
#   или: python install.py --server 148.135.203.133
# =============================================================================

import argparse
import os
import subprocess
import sys
from pathlib import Path
import urllib.request
import urllib.error


def run(cmd: str, **kwargs) -> None:
    """Запускает команду, выводя ошибку при неудаче."""
    print(f"▶ {cmd}")
    result = subprocess.run(cmd, shell=True, **kwargs)
    if result.returncode != 0:
        print(f"❌ Команда не удалась: {cmd}")
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
    run(f"{python_cmd} -m pip install httpx cryptography textual websockets pydantic-settings")


def clone_repo() -> Path:
    """Клонирует репозиторий и возвращает путь к нему."""
    home = Path.home()
    repo_dir = home / "darkmage_cli"
    if repo_dir.exists():
        import shutil
        shutil.rmtree(repo_dir)
    print("▶ Клонирование darkmage_cli...")
    run(f"git clone https://github.com/daremon7584-blip/darkmage_cli.git \"{repo_dir}\"")
    return repo_dir


def install_cli(python_cmd: str, repo_dir: Path) -> None:
    """Устанавливает CLI как команду."""
    print("▶ Установка команды darkmage...")
    run(f'cd "{repo_dir}" && {python_cmd} -m pip install -e .')


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
