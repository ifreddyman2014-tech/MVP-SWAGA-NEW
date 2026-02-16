#!/bin/bash
# Быстрый запуск бота

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "SWAGA VPN Bot - Запуск"
echo "========================================"
echo ""

# Перейти в директорию
cd /root/MVP-SWAGA-NEW 2>/dev/null || cd ~/MVP-SWAGA-NEW 2>/dev/null || {
    echo -e "${RED}Ошибка: Директория MVP-SWAGA-NEW не найдена${NC}"
    exit 1
}

# Остановить старые процессы
echo -e "${YELLOW}Остановка старых процессов...${NC}"
pkill -f "python.*main.py" 2>/dev/null || true
pkill -f "python.*bot.py" 2>/dev/null || true
systemctl stop vpnbot 2>/dev/null || true
sleep 2
echo -e "${GREEN}✓ Старые процессы остановлены${NC}"
echo ""

# Проверить версию кода
echo -e "${YELLOW}Текущая версия:${NC}"
git log -1 --oneline
echo ""

# Выбор метода запуска
echo -e "${YELLOW}Как запустить бота?${NC}"
echo "  1) Через systemd (рекомендуется)"
echo "  2) Напрямую в фоне (nohup)"
echo "  3) Напрямую в терминале (для отладки)"
echo ""
read -p "Выберите вариант [1-3]: " choice

case $choice in
    1)
        echo -e "${YELLOW}Запуск через systemd...${NC}"
        systemctl start vpnbot
        echo -e "${GREEN}✓ Бот запущен${NC}"
        echo ""
        echo "Для просмотра логов выполните:"
        echo "  journalctl -u vpnbot -f"
        echo ""
        echo "Проверка статуса:"
        sleep 2
        systemctl status vpnbot --no-pager | head -15
        ;;
    2)
        echo -e "${YELLOW}Запуск в фоне...${NC}"
        nohup python3 main.py > bot.log 2>&1 &
        PID=$!
        echo -e "${GREEN}✓ Бот запущен (PID: $PID)${NC}"
        echo ""
        echo "Для просмотра логов выполните:"
        echo "  tail -f bot.log"
        echo ""
        echo "Для остановки:"
        echo "  kill $PID"
        echo ""
        sleep 3
        echo "Последние логи:"
        tail -10 bot.log
        ;;
    3)
        echo -e "${YELLOW}Запуск в терминале (Ctrl+C для остановки)...${NC}"
        echo ""
        python3 main.py
        ;;
    *)
        echo -e "${RED}Неверный выбор${NC}"
        exit 1
        ;;
esac

echo ""
echo "========================================"
echo -e "${GREEN}Готово!${NC}"
echo "========================================"
