#!/bin/bash

# 🚀 Скрипт деплоя на продакшн

set -e  # Остановить при ошибке

echo "================================================================================"
echo "🚀 ДЕПЛОЙ SUBSCRIPTION MANAGEMENT НА ПРОДАКШН"
echo "================================================================================"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для вывода с цветом
info() {
    echo -e "${GREEN}✅ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

# Проверка, что находимся в правильной директории
if [ ! -f "vpn_bot.db" ]; then
    error "Файл vpn_bot.db не найден! Запустите скрипт из директории проекта."
    exit 1
fi

# Шаг 1: Бэкап базы данных
echo ""
echo "1️⃣ Создание бэкапа базы данных..."
BACKUP_FILE="vpn_bot.db.backup.$(date +%Y%m%d_%H%M%S)"
cp vpn_bot.db "$BACKUP_FILE"
info "Бэкап создан: $BACKUP_FILE"

# Шаг 2: Проверка текущей ветки
echo ""
echo "2️⃣ Проверка git статуса..."
CURRENT_BRANCH=$(git branch --show-current)
info "Текущая ветка: $CURRENT_BRANCH"

# Шаг 3: Получение изменений
echo ""
echo "3️⃣ Получение изменений из GitHub..."
git fetch origin
info "Изменения получены"

# Шаг 4: Merge изменений
echo ""
echo "4️⃣ Применение изменений..."
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
    warn "Вы на ветке main/master"
    read -p "Хотите смержить claude/check-status-bH5rv? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git merge origin/claude/check-status-bH5rv
        info "Изменения смержены"
    else
        info "Merge пропущен"
    fi
else
    git pull origin claude/check-status-bH5rv
    info "Изменения применены"
fi

# Шаг 5: Проверка зависимостей
echo ""
echo "5️⃣ Проверка Python зависимостей..."
if command -v pip3 &> /dev/null; then
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt --quiet
        info "Зависимости обновлены"
    else
        warn "requirements.txt не найден, пропускаем"
    fi
else
    warn "pip3 не найден, пропускаем установку зависимостей"
fi

# Шаг 6: Проверка работоспособности
echo ""
echo "6️⃣ Проверка работоспособности скриптов..."
if python3 check_subscriptions_status.py > /dev/null 2>&1; then
    info "check_subscriptions_status.py работает"
else
    error "check_subscriptions_status.py НЕ работает!"
    exit 1
fi

# Шаг 7: Показать состояние подписок
echo ""
echo "7️⃣ Текущее состояние подписок:"
echo "================================================================================"
python3 check_subscriptions_status.py

# Шаг 8: Спросить о первичном импорте
echo ""
echo "================================================================================"
read -p "8️⃣ Хотите импортировать подписки с x-ui панелей? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Dry-run импорта..."
    python3 sync_all_subscriptions.py --dry-run
    echo ""
    read -p "   Продолжить импорт? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        python3 sync_all_subscriptions.py
        info "Импорт завершён"
    else
        info "Импорт отменён"
    fi
else
    info "Импорт пропущен"
fi

# Шаг 9: Спросить о настройке cron
echo ""
echo "================================================================================"
read -p "9️⃣ Хотите настроить автоматическое продление через cron? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Добавьте в crontab:"
    echo "   crontab -e"
    echo ""
    echo "   # Продление каждую неделю (воскресенье в 3:00)"
    echo "   0 3 * * 0 cd $(pwd) && python3 bulk_extend_subscriptions.py --days-before 14 --extend-days 30 >> /var/log/vpn-extend.log 2>&1"
    echo ""
    warn "Настройте cron вручную"
else
    info "Настройка cron пропущена"
fi

# Итог
echo ""
echo "================================================================================"
echo "🎉 ДЕПЛОЙ ЗАВЕРШЁН УСПЕШНО!"
echo "================================================================================"
echo ""
info "Бэкап базы данных: $BACKUP_FILE"
info "Новые скрипты доступны:"
echo "   - python3 check_subscriptions_status.py"
echo "   - python3 bulk_extend_subscriptions.py"
echo "   - python3 sync_all_subscriptions.py"
echo ""
info "Документация:"
echo "   - cat SUBSCRIPTION_MANAGEMENT.md"
echo "   - cat QUICKSTART.md"
echo ""
warn "Не забудьте продлить UUID на x-ui панели вручную (если нужно)"
echo ""
echo "================================================================================"

