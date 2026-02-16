# Исправление ошибки 502 Bad Gateway

## Проблема

При обращении к `https://sub.swaga-vpn.ru/connect/{sub_id}` возникает ошибка **502 Bad Gateway**.

## Причина

Ошибка 502 означает, что NGINX не может проксировать запрос к backend серверу. В нашем случае:

- **NGINX** (порт 443) пытается проксировать запросы `/connect/` и `/sub/` к `http://127.0.0.1:8888`
- **Subscription server** (должен работать на порту 8888) не запущен или не отвечает

## Диагностика

Используйте скрипт для автоматической диагностики:

```bash
cd /root/MVP-SWAGA-NEW  # или путь к проекту
./check_sub_server.sh
```

Скрипт проверит:
- ✅ Запущен ли процесс бота
- ✅ Запущен ли Docker контейнер
- ✅ Слушает ли порт 8888
- ✅ Отвечает ли health endpoint
- ✅ Работают ли основные endpoints
- ✅ Логи на наличие ошибок

### Ручная диагностика

1. **Проверить, запущен ли бот:**
   ```bash
   # Через systemd
   systemctl status vpnbot

   # Через Docker
   docker ps | grep swaga

   # Процессы Python
   ps aux | grep "bot.py\|main.py"
   ```

2. **Проверить порт 8888:**
   ```bash
   ss -tlnp | grep 8888
   # или
   netstat -tlnp | grep 8888
   ```

3. **Проверить health endpoint:**
   ```bash
   curl http://127.0.0.1:8888/health
   # Должно вернуть: OK
   ```

4. **Проверить connect endpoint:**
   ```bash
   curl -I http://127.0.0.1:8888/connect/test123
   # Должно вернуть: HTTP/1.1 404 или 403 (это нормально для несуществующего ID)
   ```

## Решение

### Вариант 1: Через Docker (рекомендуется)

```bash
cd /root/MVP-SWAGA-NEW

# Пересобрать и запустить
docker-compose down
docker-compose up -d

# Проверить логи
docker-compose logs -f
```

Смотрите в логах строки:
```
Subscription server started on 127.0.0.1:8888
```

### Вариант 2: Через systemd

```bash
# Перезапустить сервис
sudo systemctl restart vpnbot

# Проверить статус
sudo systemctl status vpnbot

# Смотреть логи в реальном времени
sudo journalctl -u vpnbot -f
```

### Вариант 3: Напрямую (для отладки)

```bash
cd /root/MVP-SWAGA-NEW

# Остановить существующие процессы
pkill -f "python.*bot.py"

# Запустить с выводом в консоль
python3 bot.py

# Или в фоне с логированием
nohup python3 bot.py > bot.log 2>&1 &
tail -f bot.log
```

## Проверка после запуска

1. **Убедиться, что subscription server запустился:**
   ```bash
   curl http://127.0.0.1:8888/health
   ```
   Должно вернуть: `OK`

2. **Проверить через NGINX (с сервера):**
   ```bash
   curl -I https://sub.swaga-vpn.ru/health
   ```
   Должно вернуть: `HTTP/2 200`

3. **Проверить connect endpoint:**
   ```bash
   # С сервера (локально)
   curl http://127.0.0.1:8888/connect/test123

   # Через интернет
   curl https://sub.swaga-vpn.ru/connect/test123
   ```

## Частые проблемы

### 1. Порт 8888 занят другим процессом

```bash
# Найти процесс
lsof -i :8888

# Убить процесс (замените PID)
kill -9 <PID>

# Перезапустить бота
sudo systemctl restart vpnbot
```

### 2. Subscription server не стартует из-за ошибки в коде

```bash
# Проверить логи
sudo journalctl -u vpnbot -n 50 | grep -i error

# Или Docker логи
docker logs swaga_vpn_bot | grep -i error
```

### 3. Неверная конфигурация SUB_LISTEN_PORT

```bash
# Проверить .env
grep SUB_LISTEN_PORT .env

# Должно быть:
SUB_LISTEN_PORT=8888
```

Если значение другое:
1. Исправьте в `.env`
2. Перезапустите бота

### 4. NGINX не может подключиться к 127.0.0.1:8888

Проверьте конфигурацию NGINX:
```bash
sudo nginx -t
sudo nginx -T | grep -A 10 "server_name sub.swaga-vpn.ru"
```

Должно быть:
```nginx
location /connect/ {
    proxy_pass http://127.0.0.1:8888/connect/;
    ...
}
```

### 5. Firewall блокирует внутренний трафик

```bash
# Проверить правила
sudo iptables -L -n | grep 8888

# Если нужно, добавить правило
sudo iptables -A INPUT -p tcp --dport 8888 -s 127.0.0.1 -j ACCEPT
```

## Архитектура

```
Клиент (интернет)
    ↓
HTTPS (443) → NGINX (sub.swaga-vpn.ru)
    ↓
Proxy → http://127.0.0.1:8888 (Subscription Server)
    ↓
Python aiohttp (sub_app.py)
    ↓
Обработка /sub/{id} и /connect/{id}
```

## Мониторинг

После устранения проблемы настройте мониторинг:

### Health Check endpoint

```bash
# Локально
curl http://127.0.0.1:8888/health

# Через NGINX
curl https://sub.swaga-vpn.ru/health
```

### Автоматический мониторинг (cron)

Создайте скрипт `/root/check_sub_health.sh`:
```bash
#!/bin/bash
if ! curl -sf http://127.0.0.1:8888/health > /dev/null; then
    echo "$(date): Subscription server не отвечает, перезапуск..." >> /var/log/sub_health.log
    systemctl restart vpnbot
fi
```

Добавьте в crontab:
```bash
crontab -e

# Добавьте строку (проверка каждые 5 минут)
*/5 * * * * /root/check_sub_health.sh
```

## Дополнительная информация

- **Порт subscription server:** 8888 (локальный, не доступен извне)
- **NGINX config:** `/etc/nginx/sites-available/swaga-vpn.ru`
- **Код subscription server:** `sub_app.py`
- **Точка запуска:** `bot.py` → `start_sub_server()`
- **Health endpoint:** `/health` (возвращает "OK")

## Контакты

При возникновении проблем проверьте:
1. Логи бота: `sudo journalctl -u vpnbot -n 100`
2. Логи NGINX: `sudo tail -f /var/log/nginx/error.log`
3. Системные ресурсы: `htop`, `df -h`, `free -h`
