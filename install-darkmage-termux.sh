#!/bin/bash
# =============================================================================
# Darkmage AI CLI — установочный скрипт для Termux (Android)
# =============================================================================
# Использование:
#   curl -sSL https://raw.githubusercontent.com/daremon7584-blip/darkmage_cli/main/install-darkmage-termux.sh | bash
# =============================================================================

set -e

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  🧙‍♂️  Darkmage AI CLI — установка для Termux                      ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""

# 1. Исправляем возможные ошибки dpkg (вопрос про bash.bashrc)
echo "▶ Проверка состояния пакетов..."
echo "N" | dpkg --configure -a 2>/dev/null || true
apt-get install -y --fix-broken 2>/dev/null || true

# 2. Обновляем пакеты
echo "▶ Обновление пакетов Termux..."
pkg update -y
pkg upgrade -y

# 3. Устанавливаем зависимости
echo "▶ Установка Python, git и инструментов сборки..."
pkg install -y python git build-essential rust libffi openssl curl

# 4. Обновляем pip
echo "▶ Обновление pip..."
pip install --upgrade pip

# 5. Устанавливаем Python зависимости Darkmage CLI
echo "▶ Установка Python зависимостей..."
pip install httpx cryptography textual websockets pydantic-settings

# 6. Клонируем репозиторий
echo "▶ Клонирование darkmage_cli..."
cd ~
rm -rf darkmage_cli
git clone https://github.com/daremon7584-blip/darkmage_cli.git
cd darkmage_cli

# 7. Устанавливаем CLI как команду darkmage
echo "▶ Установка команды darkmage..."
pip install -e .

# 8. Настраиваем переменные окружения
echo "▶ Настройка переменных окружения..."

if ! grep -q "DARKMAGE_API_URL" ~/.bashrc 2>/dev/null; then
    echo '' >> ~/.bashrc
    echo '# Darkmage AI CLI configuration' >> ~/.bashrc
    echo 'export DARKMAGE_API_URL="http://ВАШ_СЕРВЕР:8000"' >> ~/.bashrc
    echo 'export DARKMAGE_TOKEN=""' >> ~/.bashrc
    echo 'export DARKMAGE_RUNNER_URL="http://ВАШ_СЕРВЕР:8090"' >> ~/.bashrc
    echo 'export DARKMAGE_RUNNER_TOKEN=""' >> ~/.bashrc
fi

source ~/.bashrc

# 9. Готово
echo ""
echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  ✅ Установка завершена!                                            ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "  1. Отредактируйте DARKMAGE_API_URL в ~/.bashrc:"
echo "     nano ~/.bashrc"
echo ""
echo "  2. Примените изменения:"
echo "     source ~/.bashrc"
echo ""
echo "  3. Первый вход (создаст аккаунт или войдёт в существующий):"
echo "     darkmage auth interactive"
echo ""
echo "  4. Посмотреть рабочие зоны:"
echo "     darkmage workspace list"
echo ""
echo "  5. Запустить TUI для рабочей зоны:"
echo "     darkmage tui <workspace_id>"
echo ""
echo "⚠️  Важно: замените ВАШ_СЕРВЕР на реальный IP или домен вашего бэкенда"
echo "     Darkmage AI. Если бэкенд на localhost компьютера, с телефона"
echo "     он недоступен — нужен публичный IP или домен."
echo ""
