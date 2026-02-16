# Быстрое обновление на production

Для исправления ошибки "Health check failed for Латвия" выполните на сервере:

## Вариант 1: Автоматический (рекомендуется)

```bash
ssh root@your-server
cd /root/MVP-SWAGA-NEW

# Скачать и запустить скрипт обновления
git pull origin claude/check-status-bH5rv
chmod +x deploy.sh
./deploy.sh
```

## Вариант 2: Ручной

```bash
ssh root@your-server
cd /root/MVP-SWAGA-NEW

# 1. Остановить бота
systemctl stop vpnbot
# или
pkill -f "python.*main.py"

# 2. Обновить код
git fetch origin
git pull origin claude/check-status-bH5rv

# 3. Установить зависимости (если нужно)
pip3 install -r requirements.txt

# 4. Запустить бота
systemctl start vpnbot
# или
nohup python3 main.py > bot.log 2>&1 &

# 5. Проверить логи
tail -f bot.log
# или
journalctl -u vpnbot -f
```

## Что будет исправлено:

✅ **HTTPS для порта 2053**: Теперь health check использует HTTPS для стандартных портов (443, 2053, 2083, 2096, 8443)

✅ **Исправлен двойной слеш**: URL теперь правильно формируется без `//login`

✅ **Новые зависимости**: SQLAlchemy, asyncpg, pydantic для sync_servers.py

## Проверка после обновления:

```bash
# Посмотреть логи
tail -f bot.log

# Вы должны увидеть:
# [INFO] Health check: 3/3 серверов онлайн  ← Все серверы работают!
```

## Если остались проблемы:

```bash
# Проверить версию кода
cd /root/MVP-SWAGA-NEW
git log -1 --oneline

# Должно быть:
# 9de3f69 Add quick deployment guide and automation script

# Проверить конфигурацию серверов
cat servers.json | grep -A 10 '"name": "Латвия"'

# Должно быть:
# "xui_port": 2053,  ← Будет использоваться HTTPS
# "xui_web_path": "/",  ← Не будет двойного слеша
```

## Откат (если что-то пошло не так):

```bash
cd /root/MVP-SWAGA-NEW
git checkout master
systemctl restart vpnbot
```
