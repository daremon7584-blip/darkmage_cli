#!/bin/bash
# =============================================================================
# Darkmage AI CLI — установочный скрипт для Termux (Android)
# =============================================================================
# Использование (предпочтительно — из проверенного локального checkout):
#   bash install-darkmage-termux.sh <IP_СЕРВЕРА>
#   или: DARKMAGE_SERVER=148.135.203.133 ./install-darkmage-termux.sh
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
    echo "║  🧙‍♂️  Darkmage AI CLI — установка для Termux                      ║"
    echo "╚════════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "⚠️  Укажите IP сервера: curl -sSL ... | bash -s -- <IP>"
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
echo "║  🧙‍♂️  Darkmage AI CLI — установка для Termux                      ║"
echo "║  Сервер: $SERVER                                                      ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 1. Исправляем возможные ошибки dpkg (вопрос про bash.bashrc)
echo "▶ Проверка пакетов..."
echo "N" | dpkg --configure -a 2>/dev/null || true
apt-get install -y --fix-broken 2>/dev/null || true

# 2. Устанавливаем зависимости (без pip upgrade — запрещено в Termux)
echo "▶ Установка Python, git, curl..."
pkg update -y
pkg install -y python git rust libffi openssl curl

# 3. Устанавливаем Python зависимости
echo "▶ Установка Python зависимостей..."
python -m pip install httpx cryptography textual websockets pydantic-settings

# 4. Клонируем или обновляем репозиторий (без удаления каталога)
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

# 5. Устанавливаем CLI как команду darkmage
echo "▶ Установка команды darkmage..."
python -m pip install -e .

# 6. Настраиваем переменные окружения (с вашим сервером)
echo "▶ Настройка ~/.bashrc..."
if ! grep -q "DARKMAGE_API_URL" ~/.bashrc 2>/dev/null; then
    echo '' >> ~/.bashrc
    echo '# Darkmage AI CLI configuration' >> ~/.bashrc
    echo "export DARKMAGE_API_URL=\"http://$SERVER:8000\"" >> ~/.bashrc
    echo 'export DARKMAGE_TOKEN=""' >> ~/.bashrc
    echo "export DARKMAGE_RUNNER_URL=\"http://$SERVER:8090\"" >> ~/.bashrc
    echo 'export DARKMAGE_RUNNER_TOKEN=""' >> ~/.bashrc
fi
source ~/.bashrc

# 7. Готово
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
