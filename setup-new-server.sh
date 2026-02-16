#!/bin/bash
# Скрипт автоматической установки и настройки 3X-UI панели для SWAGA VPN
# Сервер: vm1484131.vds.chsl.one (144.31.132.116)
#
# Использование:
#   ssh root@144.31.132.116 'bash -s' < setup-new-server.sh

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Настройка нового VPN сервера SWAGA ===${NC}"
echo ""

# Информация о сервере
SERVER_IP="144.31.132.116"
SERVER_DOMAIN="vm1484131.vds.chsl.one"

# Генерация случайных паролей для 3X-UI
XUI_USERNAME="admin-$(openssl rand -hex 4)"
XUI_PASSWORD="$(openssl rand -base64 16)"
XUI_WEB_PATH="/$(openssl rand -hex 8)"

echo -e "${YELLOW}[1/10] Обновление системы...${NC}"
apt-get update
apt-get upgrade -y
apt-get install -y curl wget socat git ufw

echo -e "${YELLOW}[2/10] Настройка файрвола...${NC}"
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw allow 2053/tcp  # 3X-UI Panel
ufw allow 19571/tcp # VPN Port
ufw reload
echo -e "${GREEN}Файрвол настроен${NC}"

echo -e "${YELLOW}[3/10] Установка 3X-UI панели (MHSanaei)...${NC}"
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh) << EOF
n
EOF

# Ждем пока панель запустится
sleep 5

echo -e "${YELLOW}[4/10] Настройка 3X-UI панели...${NC}"

# Создаем конфигурационный файл для 3X-UI
cat > /usr/local/x-ui/config.json << EOF
{
  "listen": "0.0.0.0",
  "port": 2053,
  "webPath": "${XUI_WEB_PATH}",
  "username": "${XUI_USERNAME}",
  "password": "${XUI_PASSWORD}",
  "cert": {
    "certFile": "",
    "keyFile": ""
  }
}
EOF

# Перезапускаем 3X-UI с новыми настройками
systemctl restart x-ui

echo -e "${YELLOW}[5/10] Ожидание запуска панели...${NC}"
sleep 10

# Проверяем что панель запущена
if systemctl is-active --quiet x-ui; then
    echo -e "${GREEN}3X-UI панель успешно запущена${NC}"
else
    echo -e "${RED}ОШИБКА: 3X-UI панель не запустилась${NC}"
    exit 1
fi

echo -e "${YELLOW}[6/10] Генерация Reality ключей...${NC}"
# Генерируем Reality ключи через x-ui
REALITY_KEYS=$(/usr/local/x-ui/bin/xray-linux-amd64 x25519)
REALITY_PRIVATE_KEY=$(echo "$REALITY_KEYS" | grep "Private key:" | awk '{print $3}')
REALITY_PUBLIC_KEY=$(echo "$REALITY_KEYS" | grep "Public key:" | awk '{print $3}')

echo -e "${GREEN}Reality ключи сгенерированы${NC}"
echo "Private Key: $REALITY_PRIVATE_KEY"
echo "Public Key: $REALITY_PUBLIC_KEY"

echo -e "${YELLOW}[7/10] Генерация Reality Short ID...${NC}"
REALITY_SHORT_ID=$(openssl rand -hex 8)
echo "Short ID: $REALITY_SHORT_ID"

echo -e "${YELLOW}[8/10] Установка базовых настроек безопасности...${NC}"

# Отключаем IPv6 (опционально, для безопасности)
echo "net.ipv6.conf.all.disable_ipv6 = 1" >> /etc/sysctl.conf
echo "net.ipv6.conf.default.disable_ipv6 = 1" >> /etc/sysctl.conf
sysctl -p

# Настраиваем BBR для улучшения производительности TCP
echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
sysctl -p

echo -e "${YELLOW}[9/10] Создание файла с параметрами сервера...${NC}"

# Сохраняем все параметры в файл
cat > /root/server-config.txt << EOF
=== Параметры нового VPN сервера SWAGA ===

Сервер: $SERVER_DOMAIN
IP: $SERVER_IP

=== 3X-UI Панель ===
URL: http://$SERVER_IP:2053${XUI_WEB_PATH}
Альтернативный URL: http://$SERVER_DOMAIN:2053${XUI_WEB_PATH}
Username: $XUI_USERNAME
Password: $XUI_PASSWORD
Port: 2053

=== Reality Configuration ===
Public Key: $REALITY_PUBLIC_KEY
Private Key: $REALITY_PRIVATE_KEY
Short ID: $REALITY_SHORT_ID

=== VPN Port ===
Port: 19571

=== Рекомендуемые настройки VLESS Inbound ===
Protocol: VLESS
Security: Reality
Transport: XHTTP
XHTTP Host: yandex.ru
XHTTP Path: /adv
XHTTP Mode: packet-up
Reality SNI: yandex.ru (или другой популярный домен)
Reality Fingerprint: chrome

=== Следующие шаги ===
1. Войдите в панель 3X-UI по адресу выше
2. Создайте новый VLESS Inbound с настройками Reality + XHTTP
3. Используйте сгенерированные Reality ключи
4. Добавьте сервер в servers.json проекта SWAGA
5. Перезапустите бота

=== ВАЖНО ===
Сохраните эти данные в надежном месте!
Файл с конфигурацией: /root/server-config.txt

EOF

cat /root/server-config.txt

echo ""
echo -e "${YELLOW}[10/10] Финальная проверка...${NC}"

# Проверяем статус сервисов
echo -e "${GREEN}Статус 3X-UI:${NC}"
systemctl status x-ui --no-pager | head -5

echo ""
echo -e "${GREEN}=== Установка завершена! ===${NC}"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo "1. Войдите в панель 3X-UI:"
echo "   URL: http://$SERVER_IP:2053${XUI_WEB_PATH}"
echo "   Username: $XUI_USERNAME"
echo "   Password: $XUI_PASSWORD"
echo ""
echo "2. Создайте VLESS Inbound с Reality + XHTTP"
echo ""
echo "3. Все параметры сохранены в: /root/server-config.txt"
echo ""
echo -e "${GREEN}Готово!${NC}"
