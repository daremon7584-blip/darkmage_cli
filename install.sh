#!/bin/bash
# =============================================================================
# Darkmage AI CLI — универсальный установщик (Linux / macOS / Termux / WSL)
# =============================================================================
# Использование (предпочтительно — из проверенного локального checkout):
#   bash install.sh <IP_СЕРВЕРА>
#   или: DARKMAGE_SERVER=148.135.203.133 ./install.sh
#
# `curl | bash` остаётся совместимым, но не проверяет checksum скрипта:
# полный supply-chain pinning отложен (см. SECURITY.md).
# =============================================================================

set -e

REPO_URL="https://github.com/daremon7584-blip/darkmage_cli.git"
REPO_DIR="$HOME/darkmage_cli"
SERVER="${1:-${DARKMAGE_SERVER:-}}"

validate_server() {
    case "$1" in
        "")
            echo "❌ Пустой адрес сервера." >&2
            exit 2
            ;;
        *[!A-Za-z0-9.-]*|.*|-*|*.|*..*)
            echo "❌ Некорректный адрес сервера: разрешены только буквы, цифры, точки и дефис." >&2
            exit 2
            ;;
    esac
    if [ "${#1}" -gt 253 ]; then
        echo "❌ Слишком длинный адрес сервера." >&2
        exit 2
    fi
}

if [ -z "$SERVER" ]; then
    echo "╔════════════════════════════════════════════════════════════════════╗"
    echo "║  🧙‍♂️  Darkmage AI CLI — установка                                ║"
    echo "╚════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "⚠️  Укажите IP или домен сервера:"
    echo "   curl -sSL ... | bash -s -- <IP_СЕРВЕРА>"
    echo "   Пример: curl -sSL ... | bash -s -- 148.135.203.133"
    echo ""
    exit 1
fi

validate_server "$SERVER"

# Internal safe test hook: validates input without installing anything.
if [ "${DARKMAGE_INSTALL_DRY_RUN:-0}" = "1" ]; then
    echo "✅ Server validation passed: $SERVER"
    exit 0
fi

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  🧙‍♂️  Darkmage AI CLI — установка                                ║"
echo "║  Сервер: $SERVER                                                       ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# --- Health-check сервера ---
echo "▶ Проверка сервера $SERVER:8000..."
if command -v curl >/dev/null 2>&1; then
    if curl -sSf --max-time 10 "http://$SERVER:8000/health" >/dev/null 2>&1; then
        echo "   ✅ Сервер отвечает"
    else
        echo "   ⚠️  Сервер не отвечает на http://$SERVER:8000/health"
        echo "      Установка продолжится, но проверьте, что сервер запущен."
    fi
else
    echo "   ⚠️  curl не найден, пропускаем проверку сервера."
fi
echo ""

# --- Определяем ОС и пакетный менеджер ---
OS="$(uname -s)"
ARCH="$(uname -m)"
echo "▶ Платформа: $OS $ARCH"

install_python_pkgs() {
    echo "▶ Установка Python зависимостей..."
    if command -v python3 >/dev/null 2>&1; then
        PY=python3
    elif command -v python >/dev/null 2>&1; then
        PY=python
    else
        echo "❌ Python не найден. Установите Python 3.10+ и запустите снова."
        exit 1
    fi

    # Устанавливаем зависимости
    "$PY" -m pip install --quiet httpx textual websockets pydantic-settings cryptography || \
        pip install --quiet httpx textual websockets pydantic-settings cryptography || \
        "$PY" -m pip install httpx textual websockets pydantic-settings cryptography

    # cryptography нужен для шифрования токена в конфиге.
    # В Termux с Python 3.14 пред собранное wheel может не совпадать с ABI
    # (символ PyBaseObject_Type отсутствует). Пробуем обычное установление,
    # а если не сработает — пересобираем из исходников.
    if ! "$PY" -c "from cryptography.fernet import Fernet" 2>/dev/null; then
        echo "▶ Пересборка cryptography из исходников (для совместимости с Python $("$PY" --version 2>&1 | cut -d' ' -f2))..."
        "$PY" -m pip install --force-reinstall --no-binary :all: cryptography || \
            pip install --force-reinstall --no-binary :all: cryptography
    fi
}

case "$OS" in
    Linux*)
        if command -v apt-get >/dev/null 2>&1; then
            echo "▶ Установка через apt..."
            apt-get update -y
            apt-get install -y python3 python3-pip git curl libffi-dev openssl
            install_python_pkgs
        elif command -v pkg >/dev/null 2>&1; then
            echo "▶ Установка через pkg (Termux)..."
            pkg update -y
            pkg install -y python git rust libffi openssl curl
            install_python_pkgs
        elif command -v dnf >/dev/null 2>&1; then
            echo "▶ Установка через dnf..."
            dnf install -y python3 python3-pip git curl libffi-devel openssl-devel
            install_python_pkgs
        elif command -v yum >/dev/null 2>&1; then
            echo "▶ Установка через yum..."
            yum install -y python3 python3-pip git curl libffi-devel openssl-devel
            install_python_pkgs
        elif command -v pacman >/dev/null 2>&1; then
            echo "▶ Установка через pacman..."
            pacman -Sy --noconfirm python python-pip git curl libffi openssl
            install_python_pkgs
        else
            echo "❌ Неизвестный пакетный менеджер. Установите Python 3.10+ вручную."
            exit 1
        fi
        ;;
    Darwin*)
        echo "▶ Установка через Homebrew (macOS)..."
        if ! command -v brew >/dev/null 2>&1; then
            echo "❌ Homebrew не найден. Установите brew с https://brew.sh"
            exit 1
        fi
        brew install python git curl libffi openssl
        install_python_pkgs
        ;;
    *)
        echo "❌ Платформа $OS не поддерживается этим скриптом."
        echo "   Используйте install.py для Windows или установите вручную."
        exit 1
        ;;
esac

# --- Клонируем или обновляем репозиторий (без удаления каталога) ---
echo "▶ Клонирование/обновление darkmage_cli..."
if [ -e "$REPO_DIR" ]; then
    if [ ! -d "$REPO_DIR/.git" ]; then
        echo "❌ $REPO_DIR уже существует, но это не git-клон." >&2
        echo "   Переместите или удалите его вручную и запустите установку снова." >&2
        exit 2
    fi
    ORIGIN="$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)"
    if [ "$ORIGIN" != "$REPO_URL" ]; then
        echo "❌ $REPO_DIR указывает на другой remote: ${ORIGIN:-<none>}" >&2
        exit 2
    fi
    git -C "$REPO_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# --- Устанавливаем CLI ---
echo "▶ Установка команды darkmage..."
python -m pip install -e . 2>/dev/null || pip install -e . 2>/dev/null || python3 -m pip install -e .

# --- Настраиваем переменные окружения ---
RC_FILE="$HOME/.bashrc"
if [ "$OS" = "Darwin" ]; then
    RC_FILE="$HOME/.zshrc"
fi

echo "▶ Настройка $RC_FILE..."
if ! grep -q "DARKMAGE_API_URL" "$RC_FILE" 2>/dev/null; then
    echo '' >> "$RC_FILE"
    echo '# Darkmage AI CLI configuration' >> "$RC_FILE"
    echo "export DARKMAGE_API_URL=\"http://$SERVER:8000\"" >> "$RC_FILE"
    echo 'export DARKMAGE_TOKEN=""' >> "$RC_FILE"
    echo "export DARKMAGE_RUNNER_URL=\"http://$SERVER:8090\"" >> "$RC_FILE"
    echo 'export DARKMAGE_RUNNER_TOKEN=""' >> "$RC_FILE"
fi
source "$RC_FILE" 2>/dev/null || true

# --- Готово ---
echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ Установка завершена!                                            ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "  1. Первый вход (создаст аккаунт или войдёт в существующий):"
echo "     darkmage auth interactive"
echo ""
echo "  2. Посмотреть рабочие зоны:"
echo "     darkmage workspace list"
echo ""
echo "  3. Запустить TUI для рабочей зоны:"
echo "     darkmage tui <workspace_id>"
echo ""
echo "🌐 Сервер API: http://$SERVER:8000"
echo ""
