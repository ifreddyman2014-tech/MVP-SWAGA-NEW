#!/bin/bash
# Скрипт диагностики subscription server (порт 8888)

echo "========================================"
echo "SWAGA VPN - Диагностика Subscription Server"
echo "========================================"
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Переменные
SUB_PORT=8888
SUB_URL="http://127.0.0.1:$SUB_PORT"

# 1. Проверка процесса бота
echo -e "${BLUE}1. Проверка процесса бота...${NC}"
BOT_PIDS=$(pgrep -f "python.*bot\.py" || pgrep -f "python.*main\.py")
if [ -n "$BOT_PIDS" ]; then
    echo -e "${GREEN}✓ Бот запущен (PID: $BOT_PIDS)${NC}"
    ps -p $BOT_PIDS -o pid,ppid,cmd,etime
else
    echo -e "${RED}✗ Процесс бота не найден${NC}"
fi
echo ""

# 2. Проверка Docker контейнера
echo -e "${BLUE}2. Проверка Docker контейнера...${NC}"
if command -v docker &> /dev/null; then
    CONTAINER=$(docker ps --filter "name=swaga_vpn_bot" --format "{{.Names}}" 2>/dev/null)
    if [ -n "$CONTAINER" ]; then
        echo -e "${GREEN}✓ Docker контейнер запущен: $CONTAINER${NC}"
        docker ps --filter "name=swaga_vpn_bot" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        echo -e "${YELLOW}⚠ Docker контейнер не найден или остановлен${NC}"
    fi
else
    echo -e "${YELLOW}⚠ Docker не установлен${NC}"
fi
echo ""

# 3. Проверка порта 8888
echo -e "${BLUE}3. Проверка порта $SUB_PORT...${NC}"
if command -v ss &> /dev/null; then
    PORT_CHECK=$(ss -tlnp | grep ":$SUB_PORT ")
elif command -v netstat &> /dev/null; then
    PORT_CHECK=$(netstat -tlnp | grep ":$SUB_PORT ")
else
    echo -e "${YELLOW}⚠ Утилиты ss/netstat не найдены${NC}"
    PORT_CHECK=""
fi

if [ -n "$PORT_CHECK" ]; then
    echo -e "${GREEN}✓ Порт $SUB_PORT прослушивается${NC}"
    echo "$PORT_CHECK"
else
    echo -e "${RED}✗ Порт $SUB_PORT не прослушивается${NC}"
fi
echo ""

# 4. Проверка health endpoint
echo -e "${BLUE}4. Проверка health endpoint ($SUB_URL/health)...${NC}"
if command -v curl &> /dev/null; then
    HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" "$SUB_URL/health" 2>/dev/null)
    HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
    HEALTH_BODY=$(echo "$HEALTH_RESPONSE" | head -n-1)

    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✓ Health check успешен (HTTP $HTTP_CODE)${NC}"
        echo "Ответ: $HEALTH_BODY"
    else
        echo -e "${RED}✗ Health check не прошел (HTTP ${HTTP_CODE:-нет ответа})${NC}"
    fi
else
    echo -e "${YELLOW}⚠ curl не установлен, пропускаем проверку${NC}"
fi
echo ""

# 5. Проверка /connect/ endpoint
echo -e "${BLUE}5. Проверка /connect/ endpoint...${NC}"
if command -v curl &> /dev/null; then
    CONNECT_RESPONSE=$(curl -s -w "\n%{http_code}" "$SUB_URL/connect/test123" 2>/dev/null)
    HTTP_CODE=$(echo "$CONNECT_RESPONSE" | tail -n1)

    if [ "$HTTP_CODE" = "404" ] || [ "$HTTP_CODE" = "403" ]; then
        echo -e "${GREEN}✓ Endpoint /connect/ отвечает (HTTP $HTTP_CODE - нормально для теста)${NC}"
    elif [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✓ Endpoint /connect/ отвечает (HTTP $HTTP_CODE)${NC}"
    else
        echo -e "${RED}✗ Endpoint /connect/ не отвечает (HTTP ${HTTP_CODE:-нет ответа})${NC}"
    fi
fi
echo ""

# 6. Проверка логов
echo -e "${BLUE}6. Проверка логов...${NC}"

# Systemd логи
if systemctl is-active --quiet vpnbot 2>/dev/null; then
    echo -e "${YELLOW}Последние логи из systemd (vpnbot):${NC}"
    journalctl -u vpnbot -n 10 --no-pager | grep -i "subscription\|8888\|error" || echo "Нет релевантных записей"
fi

# Docker логи
if [ -n "$CONTAINER" ]; then
    echo -e "${YELLOW}Последние логи из Docker:${NC}"
    docker logs --tail 10 "$CONTAINER" 2>&1 | grep -i "subscription\|8888\|error" || echo "Нет релевантных записей"
fi

# Файловые логи
if [ -f bot.log ]; then
    echo -e "${YELLOW}Последние записи из bot.log:${NC}"
    tail -10 bot.log | grep -i "subscription\|8888\|error" || echo "Нет релевантных записей"
elif [ -f main.log ]; then
    echo -e "${YELLOW}Последние записи из main.log:${NC}"
    tail -10 main.log | grep -i "subscription\|8888\|error" || echo "Нет релевантных записей"
fi
echo ""

# 7. Диагноз и рекомендации
echo "========================================"
echo -e "${BLUE}Диагноз и рекомендации:${NC}"
echo "========================================"
echo ""

# Определяем проблему
PROBLEM_FOUND=false

if [ -z "$BOT_PIDS" ] && [ -z "$CONTAINER" ]; then
    echo -e "${RED}❌ ПРОБЛЕМА: Бот не запущен${NC}"
    echo ""
    echo "Решение:"
    echo "  1. Через Docker (рекомендуется):"
    echo "     cd /root/MVP-SWAGA-NEW  # или путь к проекту"
    echo "     docker-compose up -d"
    echo "     docker-compose logs -f"
    echo ""
    echo "  2. Через systemd:"
    echo "     sudo systemctl start vpnbot"
    echo "     sudo journalctl -u vpnbot -f"
    echo ""
    echo "  3. Напрямую (для отладки):"
    echo "     cd /root/MVP-SWAGA-NEW"
    echo "     python3 bot.py"
    PROBLEM_FOUND=true
elif [ -z "$PORT_CHECK" ]; then
    echo -e "${RED}❌ ПРОБЛЕМА: Бот запущен, но subscription server не слушает порт $SUB_PORT${NC}"
    echo ""
    echo "Возможные причины:"
    echo "  • Ошибка при запуске subscription server"
    echo "  • Порт занят другим процессом"
    echo "  • Неверная конфигурация SUB_LISTEN_PORT в .env"
    echo ""
    echo "Решение:"
    echo "  1. Проверьте логи на ошибки:"
    if [ -n "$CONTAINER" ]; then
        echo "     docker logs swaga_vpn_bot | grep -i error"
    else
        echo "     journalctl -u vpnbot -n 50 | grep -i error"
    fi
    echo ""
    echo "  2. Проверьте .env файл:"
    echo "     grep SUB_LISTEN_PORT .env  # должно быть 8888"
    echo ""
    echo "  3. Проверьте, не занят ли порт:"
    echo "     lsof -i :$SUB_PORT"
    echo ""
    echo "  4. Перезапустите бота:"
    if [ -n "$CONTAINER" ]; then
        echo "     docker-compose restart"
    else
        echo "     sudo systemctl restart vpnbot"
    fi
    PROBLEM_FOUND=true
elif [ "$HTTP_CODE" != "200" ] && command -v curl &> /dev/null; then
    echo -e "${RED}❌ ПРОБЛЕМА: Порт открыт, но health endpoint не отвечает${NC}"
    echo ""
    echo "Это может означать:"
    echo "  • Subscription server запущен, но зависает"
    echo "  • Проблемы с aiohttp или маршрутами"
    echo ""
    echo "Решение:"
    echo "  1. Перезапустите сервис:"
    if [ -n "$CONTAINER" ]; then
        echo "     docker-compose restart"
    else
        echo "     sudo systemctl restart vpnbot"
    fi
    echo ""
    echo "  2. Проверьте логи после перезапуска:"
    if [ -n "$CONTAINER" ]; then
        echo "     docker-compose logs -f"
    else
        echo "     sudo journalctl -u vpnbot -f"
    fi
    PROBLEM_FOUND=true
fi

if ! $PROBLEM_FOUND; then
    echo -e "${GREEN}✅ Subscription server работает нормально!${NC}"
    echo ""
    echo "Тестовые команды:"
    echo "  curl $SUB_URL/health"
    echo "  curl $SUB_URL/connect/test123"
    echo ""
    echo "Если всё равно видите 502 на sub.swaga-vpn.ru:"
    echo "  1. Проверьте NGINX:"
    echo "     sudo nginx -t"
    echo "     sudo systemctl status nginx"
    echo ""
    echo "  2. Проверьте NGINX конфигурацию для sub.swaga-vpn.ru:"
    echo "     sudo nginx -T | grep -A 20 'server_name sub.swaga-vpn.ru'"
    echo ""
    echo "  3. Проверьте логи NGINX:"
    echo "     sudo tail -f /var/log/nginx/error.log"
fi

echo ""
echo "========================================"
