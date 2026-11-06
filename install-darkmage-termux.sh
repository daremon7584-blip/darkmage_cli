#!/bin/bash
# =============================================================================
# Darkmage AI CLI — установочный скрипт для Termux (Android)
# =============================================================================
# Использование:
#   curl -sSL https://raw.githubusercontent.com/daremon7584-blip/darkmage_cli/main/install-darkmage-termux.sh | bash -s -- <IP_СЕРВЕРА>
#   или: DARKMAGE_SERVER=148.135.203.133 curl -sSL ... | bash
# =============================================================================

set -e

SERVER="${1:-${DARKMAGE_SERVER:-}}"

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

# 4. Клонируем репозиторий
echo "▶ Клонирование darkmage_cli..."
cd ~
rm -rf darkmage_cli
git clone https://github.com/daremon7584-blip/darkmage_cli.git
cd darkmage_cli

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
