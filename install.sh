#!/bin/bash
# =============================================================================
# Darkmage AI CLI — универсальный установщик (Linux / macOS / Termux / WSL)
# =============================================================================
# Использование:
#   curl -sSL https://raw.githubusercontent.com/daremon7584-blip/darkmage_cli/main/install.sh | bash -s -- <IP_СЕРВЕРА>
#   или: DARKMAGE_SERVER=148.135.203.133 curl -sSL ... | bash
# =============================================================================

set -e

SERVER="${1:-${DARKMAGE_SERVER:-}}"

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
    "$PY" -m pip install --quiet httpx textual websockets pydantic-settings || \
        pip install --quiet httpx textual websockets pydantic-settings || \
        "$PY" -m pip install httpx textual websockets pydantic-settings

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

# --- Клонируем репозиторий ---
echo "▶ Клонирование darkmage_cli..."
cd ~
rm -rf darkmage_cli
git clone https://github.com/daremon7584-blip/darkmage_cli.git
cd darkmage_cli

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
