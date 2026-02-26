#!/bin/bash

# 🚀 БЫСТРЫЙ ДЕПЛОЙ - Запустите этот скрипт на продакшн сервере

echo "🚀 БЫСТРЫЙ ДЕПЛОЙ НА ПРОДАКШН"
echo ""
echo "Выполните эти команды на продакшн сервере:"
echo ""
echo "1️⃣ Подключитесь к серверу:"
echo "   ssh user@your-production-server"
echo ""
echo "2️⃣ Перейдите в директорию проекта:"
echo "   cd /path/to/MVP-SWAGA-NEW"
echo ""
echo "3️⃣ Получите изменения:"
echo "   git fetch origin"
echo "   git checkout claude/check-status-bH5rv"
echo ""
echo "4️⃣ Запустите деплой:"
echo "   ./deploy.sh"
echo ""
echo "ИЛИ вручную:"
echo "   cp vpn_bot.db vpn_bot.db.backup.\$(date +%Y%m%d_%H%M%S)"
echo "   git pull origin claude/check-status-bH5rv"
echo "   python3 check_subscriptions_status.py"
echo ""
echo "🎯 Готово!"

