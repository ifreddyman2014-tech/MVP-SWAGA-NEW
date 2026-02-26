#!/bin/bash
# Скрипт для быстрого наката исправлений из ветки claude/check-status-bH5rv

set -e

echo "=================================================="
echo "   Накат исправлений HTTP → HTTPS"
echo "=================================================="

# Проверяем, что мы в правильной директории
if [ ! -f "bot.py" ]; then
    echo "❌ Ошибка: запустите скрипт из директории /root/MVP-SWAGA-NEW"
    exit 1
fi

echo "▶ Текущая ветка:"
git branch --show-current

echo ""
echo "▶ Подтягиваем изменения из ветки claude/check-status-bH5rv..."
git fetch origin claude/check-status-bH5rv

echo ""
echo "▶ Мержим изменения..."
git merge origin/claude/check-status-bH5rv --no-edit

echo ""
echo "▶ Проверяем изменённые файлы..."
echo "   ✓ bulk_extend_subscriptions.py"
echo "   ✓ extend_subscription.py"
echo "   ✓ sync_all_subscriptions.py"

echo ""
echo "▶ Перезапускаем сервисы..."
if systemctl is-active --quiet swaga-bot; then
    systemctl restart swaga-bot
    echo "   ✓ swaga-bot перезапущен"
else
    echo "   ⚠ swaga-bot не запущен"
fi

if systemctl is-active --quiet swaga-support; then
    systemctl restart swaga-support
    echo "   ✓ swaga-support перезапущен"
else
    echo "   ⚠ swaga-support не запущен"
fi

echo ""
echo "=================================================="
echo "   ✅ Изменения применены!"
echo "=================================================="
echo ""
echo "Полезные команды:"
echo "  Проверка статуса:  python3 check_subscriptions_status.py"
echo "  Синхронизация:     python3 sync_all_subscriptions.py"
echo "  Логи бота:         journalctl -u swaga-bot -f"
echo "  Статус сервисов:   systemctl status swaga-bot swaga-support"
echo ""
