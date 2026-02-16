#!/bin/bash
# Скрипт для удаленной установки 3X-UI на новый сервер
#
# Использование:
#   chmod +x deploy-to-new-server.sh
#   ./deploy-to-new-server.sh

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Параметры сервера
SERVER_IP="144.31.132.116"
SERVER_USER="root"
SERVER_PASS="14GJ6H096A6d"
SERVER_DOMAIN="vm1484131.vds.chsl.one"

echo -e "${GREEN}=== Установка 3X-UI на новый сервер SWAGA ===${NC}"
echo ""
echo "Сервер: $SERVER_DOMAIN ($SERVER_IP)"
echo "Пользователь: $SERVER_USER"
echo ""

# Проверка наличия sshpass
if ! command -v sshpass &> /dev/null; then
    echo -e "${YELLOW}Установка sshpass для автоматического подключения...${NC}"

    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo apt-get update && sudo apt-get install -y sshpass
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install hudochenkov/sshpass/sshpass
    else
        echo -e "${RED}Ошибка: Пожалуйста, установите sshpass вручную${NC}"
        exit 1
    fi
fi

# Первое подключение - добавление в known_hosts
echo -e "${YELLOW}Добавление сервера в known_hosts...${NC}"
ssh-keyscan -H $SERVER_IP >> ~/.ssh/known_hosts 2>/dev/null || true

# Копирование скрипта на сервер и запуск
echo -e "${YELLOW}Копирование и запуск скрипта установки на сервере...${NC}"
echo ""

sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no ${SERVER_USER}@${SERVER_IP} 'bash -s' < setup-new-server.sh

echo ""
echo -e "${GREEN}=== Установка завершена! ===${NC}"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo ""
echo "1. Подключитесь к серверу и просмотрите конфигурацию:"
echo "   ${GREEN}ssh ${SERVER_USER}@${SERVER_IP}${NC}"
echo "   ${GREEN}cat /root/server-config.txt${NC}"
echo ""
echo "2. Войдите в панель 3X-UI через браузер"
echo "   (адрес и пароль будут в server-config.txt)"
echo ""
echo "3. Создайте VLESS Inbound с Reality + XHTTP транспортом"
echo ""
echo "4. Добавьте сервер в servers.json"
echo ""
