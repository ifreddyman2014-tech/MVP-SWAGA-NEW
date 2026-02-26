#!/bin/bash
# Исправление конфликта дублирующих bot сервисов

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m'

echo "================================================================"
echo -e "${BLUE}SWAGA VPN Bot - Исправление конфликта сервисов${NC}"
echo "================================================================"
echo ""

# Проверка прав
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Запустите скрипт с правами root: sudo $0${NC}"
    exit 1
fi

# Шаг 1: Показать текущие сервисы
echo -e "${YELLOW}📋 Проверка запущенных сервисов...${NC}"
echo ""
systemctl list-units --type=service | grep -E "swaga|vpn|bot" || echo "  Нет активных bot сервисов"
echo ""

# Шаг 2: Проверить запущенные процессы
echo -e "${YELLOW}📋 Проверка запущенных процессов...${NC}"
BOT_PROCESSES=$(ps aux | grep -E "python.*bot.py|python.*main.py" | grep -v grep | wc -l)
echo "  Найдено процессов бота: $BOT_PROCESSES"
if [ $BOT_PROCESSES -gt 1 ]; then
    echo -e "${RED}  ⚠️  КОНФЛИКТ: Запущено несколько экземпляров бота!${NC}"
fi
ps aux | grep -E "python.*bot.py|python.*main.py" | grep -v grep || echo "  Нет запущенных процессов"
echo ""

# Шаг 3: Остановить и отключить дублирующий сервис
echo -e "${YELLOW}🛑 Остановка дублирующего сервиса swaga-bot.service...${NC}"
if systemctl is-active --quiet swaga-bot.service; then
    systemctl stop swaga-bot.service
    echo -e "${GREEN}  ✓ Сервис swaga-bot.service остановлен${NC}"
else
    echo "  ℹ️  Сервис swaga-bot.service не запущен"
fi

if systemctl is-enabled --quiet swaga-bot.service 2>/dev/null; then
    systemctl disable swaga-bot.service
    echo -e "${GREEN}  ✓ Сервис swaga-bot.service отключен из автозагрузки${NC}"
else
    echo "  ℹ️  Сервис swaga-bot.service не найден или уже отключен"
fi
echo ""

# Шаг 4: Остановить все процессы бота
echo -e "${YELLOW}🛑 Остановка всех процессов бота...${NC}"
pkill -f "python.*bot.py" 2>/dev/null && echo -e "${GREEN}  ✓ Процессы bot.py остановлены${NC}" || echo "  ℹ️  Процессы bot.py не найдены"
pkill -f "python.*main.py" 2>/dev/null && echo -e "${GREEN}  ✓ Процессы main.py остановлены${NC}" || echo "  ℹ️  Процессы main.py не найдены"
sleep 2
echo ""

# Шаг 5: Отключить старый .env если существует
echo -e "${YELLOW}🔧 Проверка старого .env в /root/bot/...${NC}"
if [ -f "/root/bot/.env" ]; then
    echo -e "${YELLOW}  ⚠️  Найден старый .env файл с тем же токеном!${NC}"
    mv /root/bot/.env /root/bot/.env.disabled
    echo -e "${GREEN}  ✓ Старый .env переименован в .env.disabled${NC}"
else
    echo "  ℹ️  Старый .env не найден"
fi
echo ""

# Шаг 6: Запустить правильный сервис
echo -e "${YELLOW}🚀 Запуск сервиса vpnbot...${NC}"
if systemctl is-active --quiet vpnbot.service; then
    systemctl restart vpnbot.service
    echo -e "${GREEN}  ✓ Сервис vpnbot перезапущен${NC}"
else
    systemctl start vpnbot.service
    echo -e "${GREEN}  ✓ Сервис vpnbot запущен${NC}"
fi

# Включить автозагрузку если нужно
if ! systemctl is-enabled --quiet vpnbot.service 2>/dev/null; then
    systemctl enable vpnbot.service
    echo -e "${GREEN}  ✓ Автозагрузка vpnbot включена${NC}"
fi
echo ""

# Шаг 7: Подождать и проверить статус
echo -e "${YELLOW}⏳ Ожидание запуска (5 сек)...${NC}"
sleep 5
echo ""

# Шаг 8: Финальная проверка
echo "================================================================"
echo -e "${BLUE}📊 ФИНАЛЬНАЯ ПРОВЕРКА${NC}"
echo "================================================================"
echo ""

echo -e "${YELLOW}1. Статус сервиса vpnbot:${NC}"
systemctl status vpnbot.service --no-pager -l | head -20
echo ""

echo -e "${YELLOW}2. Запущенные процессы бота:${NC}"
FINAL_PROCESSES=$(ps aux | grep -E "python.*bot.py|python.*main.py" | grep -v grep | wc -l)
if [ $FINAL_PROCESSES -eq 1 ]; then
    echo -e "${GREEN}✅ ОТЛИЧНО: Запущен ровно 1 процесс бота${NC}"
    ps aux | grep -E "python.*bot.py|python.*main.py" | grep -v grep
elif [ $FINAL_PROCESSES -eq 0 ]; then
    echo -e "${RED}❌ ОШИБКА: Бот не запустился!${NC}"
    echo ""
    echo "Проверьте логи:"
    echo "  journalctl -u vpnbot -n 50"
elif [ $FINAL_PROCESSES -gt 1 ]; then
    echo -e "${RED}❌ КОНФЛИКТ: Запущено несколько процессов!${NC}"
    ps aux | grep -E "python.*bot.py|python.*main.py" | grep -v grep
fi
echo ""

echo -e "${YELLOW}3. Последние логи:${NC}"
journalctl -u vpnbot -n 20 --no-pager
echo ""

echo "================================================================"
if [ $FINAL_PROCESSES -eq 1 ]; then
    echo -e "${GREEN}✅ ГОТОВО! Бот успешно запущен без конфликтов${NC}"
    echo ""
    echo "Для просмотра логов в реальном времени:"
    echo "  journalctl -u vpnbot -f"
else
    echo -e "${RED}⚠️  Требуется дополнительная проверка${NC}"
    echo ""
    echo "Проверьте логи:"
    echo "  journalctl -u vpnbot -f"
fi
echo "================================================================"
