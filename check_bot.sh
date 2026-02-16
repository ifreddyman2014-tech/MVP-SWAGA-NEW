#!/bin/bash
# Скрипт диагностики и запуска бота

echo "========================================"
echo "SWAGA VPN Bot - Диагностика"
echo "========================================"
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 1. Проверка статуса systemd
echo -e "${BLUE}1. Проверка systemd сервиса...${NC}"
if systemctl is-active --quiet vpnbot; then
    echo -e "${GREEN}✓ Сервис vpnbot запущен${NC}"
    systemctl status vpnbot --no-pager | head -15
else
    echo -e "${RED}✗ Сервис vpnbot остановлен${NC}"
    echo -e "${YELLOW}Проверяем последние логи:${NC}"
    journalctl -u vpnbot -n 20 --no-pager
fi
echo ""

# 2. Проверка процессов Python
echo -e "${BLUE}2. Проверка процессов Python...${NC}"
PYTHON_PROCS=$(ps aux | grep -E "(main|bot)\.py" | grep -v grep)
if [ -z "$PYTHON_PROCS" ]; then
    echo -e "${RED}✗ Процессы Python не найдены${NC}"
else
    echo -e "${GREEN}✓ Найдены процессы:${NC}"
    echo "$PYTHON_PROCS"
fi
echo ""

# 3. Проверка версии кода
echo -e "${BLUE}3. Проверка версии кода...${NC}"
cd /root/MVP-SWAGA-NEW 2>/dev/null || cd ~/MVP-SWAGA-NEW 2>/dev/null || {
    echo -e "${RED}✗ Директория MVP-SWAGA-NEW не найдена${NC}"
    exit 1
}

CURRENT_COMMIT=$(git log -1 --oneline)
echo -e "Текущий коммит: ${GREEN}$CURRENT_COMMIT${NC}"

CURRENT_BRANCH=$(git branch --show-current)
echo -e "Текущая ветка: ${GREEN}$CURRENT_BRANCH${NC}"
echo ""

# 4. Проверка конфигурации
echo -e "${BLUE}4. Проверка конфигурации...${NC}"
if [ -f .env ]; then
    echo -e "${GREEN}✓ Файл .env найден${NC}"
    echo "BOT_TOKEN: $(grep BOT_TOKEN .env | cut -d'=' -f2 | cut -c1-20)..."
else
    echo -e "${RED}✗ Файл .env не найден${NC}"
fi

if [ -f servers.json ]; then
    echo -e "${GREEN}✓ Файл servers.json найден${NC}"
    SERVERS_COUNT=$(cat servers.json | grep -c '"id":')
    echo "Количество серверов: $SERVERS_COUNT"
else
    echo -e "${RED}✗ Файл servers.json не найден${NC}"
fi
echo ""

# 5. Проверка зависимостей
echo -e "${BLUE}5. Проверка зависимостей...${NC}"
if pip3 show sqlalchemy > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SQLAlchemy установлен${NC}"
else
    echo -e "${RED}✗ SQLAlchemy не установлен${NC}"
fi

if pip3 show asyncpg > /dev/null 2>&1; then
    echo -e "${GREEN}✓ asyncpg установлен${NC}"
else
    echo -e "${RED}✗ asyncpg не установлен${NC}"
fi
echo ""

# 6. Проверка логов
echo -e "${BLUE}6. Последние логи (если есть)...${NC}"
if [ -f bot.log ]; then
    echo -e "${YELLOW}Последние 15 строк bot.log:${NC}"
    tail -15 bot.log
elif [ -f main.log ]; then
    echo -e "${YELLOW}Последние 15 строк main.log:${NC}"
    tail -15 main.log
else
    echo -e "${YELLOW}Файлы логов не найдены${NC}"
fi
echo ""

# 7. Рекомендации
echo "========================================"
echo -e "${BLUE}Рекомендации:${NC}"
echo "========================================"

if ! systemctl is-active --quiet vpnbot && [ -z "$PYTHON_PROCS" ]; then
    echo -e "${YELLOW}Бот не запущен. Для запуска выполните:${NC}"
    echo ""
    echo "  # Вариант 1: Через systemd (рекомендуется)"
    echo "  sudo systemctl start vpnbot"
    echo "  sudo journalctl -u vpnbot -f"
    echo ""
    echo "  # Вариант 2: Напрямую"
    echo "  cd /root/MVP-SWAGA-NEW"
    echo "  nohup python3 main.py > bot.log 2>&1 &"
    echo "  tail -f bot.log"
fi

if [ "$CURRENT_BRANCH" != "claude/check-status-bH5rv" ]; then
    echo -e "${YELLOW}Вы не на ветке claude/check-status-bH5rv${NC}"
    echo "Для обновления выполните:"
    echo "  git checkout claude/check-status-bH5rv"
    echo "  git pull origin claude/check-status-bH5rv"
fi

echo ""
echo "========================================"
