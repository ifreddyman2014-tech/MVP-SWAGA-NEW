---
name: vpn-telegram-bot
description: Creating, configuring and maintaining Telegram VPN bots integrated with 3X-UI panel (VLESS/Reality/XHTTP). Use when the user asks to: add a new VPN server, fix bot startup, debug 3X-UI API, set up payments, configure subscriptions, deploy/update the bot, sync clients across servers.
---

# VPN Telegram Bot Skill (SWAGA-style)

Помощь в создании, настройке и поддержке Telegram-бота для продажи VPN-доступа на базе **3X-UI + VLESS + Reality**.

## Стек и архитектура

```
Telegram Bot (aiogram 2.x)
        │
        ├── bot.py            — точка входа, диспетчер aiogram
        ├── keyboards.py      — инлайн-клавиатуры
        ├── database.py       — aiosqlite, таблицы users/subscriptions/payments
        ├── config.py         — .env-переменные через python-dotenv
        ├── servers.py        — мультисерверный менеджер (servers.json)
        ├── xui_api.py        — REST-клиент 3X-UI панели
        ├── payment.py        — YooKassa интеграция
        ├── sub_app.py        — HTTP-сервер subscription URL (aiohttp)
        └── sync_clients_to_servers.py — CLI-синхронизация всех клиентов
```

## Переменные окружения (.env)

```ini
# Telegram
BOT_TOKEN=123456:ABC...
BOT_USERNAME=MyVpnBot
ADMIN_IDS=123456789,987654321

# 3X-UI (основной или legacy)
XUI_HOST=1.2.3.4
XUI_PORT=443
XUI_WEB_PATH=/secretpath     # БЕЗ /panel на конце
XUI_USERNAME=admin
XUI_PASSWORD=secret
INBOUND_ID=1

# VPN-подключение
VPN_HOST=1.2.3.4
VPN_PORT=19571
VPN_TRANSPORT=tcp            # tcp | xhttp | ws
VPN_PATH=/adv                # для xhttp/ws
VPN_CAMOUFLAGE_HOST=yandex.ru
VPN_XHTTP_MODE=packet-up

# Reality
REALITY_PUBLIC_KEY=ключ
REALITY_SHORT_ID=abcdef
REALITY_SNI=web.de
REALITY_FINGERPRINT=chrome   # chrome | firefox | safari | ios | android

# YooKassa
YOOKASSA_SHOP_ID=123456
YOOKASSA_SECRET_KEY=test_xxx

# Subscription server
SUB_BASE_URL=https://sub.example.com/sub/
SUB_LISTEN_PORT=8888

# Пути
DATABASE_PATH=./vpn_bot.db
BACKUP_PATH=./backups
```

## Мультисервер (servers.json)

```json
{
  "servers": [
    {
      "id": "de1",
      "name": "Германия",
      "host": "1.2.3.4",          // IP для клиентов
      "xui_host": "1.2.3.4",      // IP для API (127.0.0.1 если через SSH-туннель)
      "xui_port": 2055,
      "xui_web_path": "/secretpath",
      "xui_username": "admin",
      "xui_password": "secret",
      "vpn_port": 19571,
      "inbound_id": 1,
      "max_users": 150,
      "priority": 10,              // выше = предпочтительнее при выборе сервера
      "enabled": true,
      "location": "DE",
      "transport": "tcp",
      "flow": "xtls-rprx-vision",
      "reality_pbk": "...",
      "reality_sid": "abcdef",
      "reality_sni": "web.de",
      "reality_fp": "chrome"
    }
  ]
}
```

**Правило**: `xui_host` = `127.0.0.1` когда API доступен только локально (SSH-туннель).
`xui_host` = внешний IP когда API открыт напрямую.

## Схема БД

```sql
-- Пользователи
CREATE TABLE users (
    user_id          INTEGER PRIMARY KEY,   -- Telegram user_id
    username         TEXT,
    reg_date         TEXT    NOT NULL,
    trial_used       INTEGER DEFAULT 0,
    current_server   INTEGER DEFAULT 1,
    referred_by      INTEGER DEFAULT NULL,
    referral_bonus_given INTEGER DEFAULT 0,
    compensation_claimed INTEGER DEFAULT 0
);

-- Подписки
CREATE TABLE subscriptions (
    sub_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    plan        TEXT    NOT NULL,      -- trial | 1m | 3m | 1y
    start_date  TEXT    NOT NULL,
    end_date    TEXT    NOT NULL,
    is_active   INTEGER DEFAULT 1,
    vless_uuid  TEXT,                  -- UUID клиента в 3X-UI
    xui_sub_id  TEXT    DEFAULT '',    -- subscription ID (для sub URL)
    xui_email   TEXT    DEFAULT '',    -- email в панели (user_id@serverid)
    server_id   TEXT    DEFAULT '',    -- ID из servers.json
    reminder_sent TEXT  DEFAULT ''     -- флаг отправленного напоминания
);

-- Платежи (YooKassa)
CREATE TABLE payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id  TEXT    UNIQUE NOT NULL,
    user_id     INTEGER NOT NULL,
    amount      REAL    NOT NULL,
    plan_key    TEXT    NOT NULL,
    server_id   TEXT    DEFAULT '',
    status      TEXT    DEFAULT 'pending',
    created_at  TEXT    NOT NULL,
    paid_at     TEXT    DEFAULT NULL
);
```

## 3X-UI API — ключевые вызовы

```python
class XUIAPI:
    # Базовый URL: https://HOST:PORT/WEB_PATH
    # ВАЖНО: XUI_WEB_PATH НЕ должен содержать /panel

    def login(self) -> bool:
        # POST /login  {"username": ..., "password": ...}

    def add_client(self, inbound_id, uuid, email, sub_id, expiry_time, flow) -> bool:
        # POST /panel/api/inbounds/addClient
        # email = f"{user_id}@{server_id}"  — уникален в панели
        # expiry_time = int(datetime.timestamp() * 1000)  — миллисекунды, 0=бессрочно
        # flow = "xtls-rprx-vision"  — только для TCP/Reality

    def update_client(self, inbound_id, uuid, email, expiry_time) -> bool:
        # POST /panel/api/inbounds/updateClient/{uuid}

    def delete_client(self, inbound_id, uuid) -> bool:
        # POST /panel/api/inbounds/{inbound_id}/delClient/{uuid}

    def get_client_stats(self, email) -> dict:
        # GET /panel/api/inbounds/getClientTrafficByEmail/{email}
        # Возвращает: {"up": bytes, "down": bytes, "total": bytes, "enable": bool}
```

## VLESS-ссылка

```python
def build_vless_link(uuid, server, alias="SWAGA VPN") -> str:
    """Генерация vless:// ссылки для клиента."""
    from urllib.parse import quote

    if server.transport == "tcp":
        # VLESS + Reality + TCP
        params = (
            f"type=tcp"
            f"&security=reality"
            f"&pbk={server.reality_pbk}"
            f"&sid={server.reality_sid}"
            f"&sni={server.reality_sni}"
            f"&fp={server.reality_fp}"
            f"&flow={server.flow or 'xtls-rprx-vision'}"
        )
    elif server.transport == "xhttp":
        # VLESS + XHTTP (без TLS)
        params = (
            f"type=xhttp"
            f"&path={quote(server.transport_path)}"
            f"&host={server.transport_host}"
            f"&mode={server.xhttp_mode}"
            f"&security=none"
        )

    return f"vless://{uuid}@{server.host}:{server.vpn_port}?{params}#{quote(alias)}"
```

## Планы подписок

```python
PLANS = {
    "trial": {"name": "Пробный",   "days": 7,   "price": 0},
    "1m":    {"name": "1 месяц",   "days": 30,  "price": 130},
    "3m":    {"name": "3 месяца",  "days": 90,  "price": 350},
    "1y":    {"name": "1 год",     "days": 365, "price": 900},
}
```

## Запуск и деплой

### systemd-сервис (рекомендовано)

```ini
# /etc/systemd/system/swaga-bot.service
[Unit]
Description=SWAGA VPN Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/MVP-SWAGA-NEW
ExecStart=/usr/bin/python3 /root/MVP-SWAGA-NEW/bot.py
Restart=always
RestartSec=5
EnvironmentFile=/root/MVP-SWAGA-NEW/.env

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable swaga-bot
systemctl start swaga-bot
journalctl -u swaga-bot -f
```

### nohup (резервный)

```bash
pkill -f "python.*bot.py" 2>/dev/null || true
sleep 1
nohup /usr/bin/python3 /root/MVP-SWAGA-NEW/bot.py \
    >> /root/MVP-SWAGA-NEW/bot.log 2>&1 &
tail -f /root/MVP-SWAGA-NEW/bot.log
```

### Deploy-скрипт

```bash
# deploy.sh — порядок действий:
# 1. Сохранить .env (git pull его перезапишет)
# 2. git fetch + checkout + pull
# 3. Восстановить .env
# 4. pip install -r requirements.txt --break-system-packages
# 5. pkill старых процессов
# 6. systemctl restart / nohup fallback
# 7. sync_clients_to_servers.py
```

**Критично**: `.env` нужно исключить из git (`echo ".env" >> .gitignore`)
и сохранять перед `git pull`, иначе потеряются credentials.

## Частые проблемы и решения

### ModuleNotFoundError: No module named 'dotenv'

```bash
# Причина: python-dotenv не установлен в системный Python
pip3 install python-dotenv --break-system-packages
# или
pip3 install -r requirements.txt --break-system-packages
```

### Unit swaga-bot.service not found

```bash
# Сервис не зарегистрирован. Либо создать .service файл:
cp swaga-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable swaga-bot
# Либо запустить через nohup (см. выше)
```

### 3X-UI API возвращает 404/401

```bash
# Проверить XUI_WEB_PATH — он НЕ должен содержать /panel
# Неверно:  XUI_WEB_PATH=/mypanel/panel
# Верно:    XUI_WEB_PATH=/mypanel
#
# Проверить доступность панели:
curl -k https://HOST:PORT/WEB_PATH/login
```

### aiogram конфликт с aiohttp

```bash
# aiogram==2.25.2 требует aiohttp<3.9
# Устанавливать aiogram без зависимостей:
pip3 install aiogram==2.25.2 --no-deps --break-system-packages
```

### Бот не отвечает после деплоя

```bash
# 1. Проверить процесс
pgrep -af "python.*bot.py"

# 2. Проверить логи
tail -50 /root/MVP-SWAGA-NEW/bot.log
journalctl -u swaga-bot -n 50

# 3. Проверить .env токен
grep BOT_TOKEN /root/MVP-SWAGA-NEW/.env

# 4. Запустить вручную для диагностики
cd /root/MVP-SWAGA-NEW && python3 bot.py
```

### Клиент не появляется в 3X-UI

```bash
# Проверить sync вручную:
python3 sync_clients_to_servers.py

# Проверить API напрямую:
python3 -c "
from xui_api import XUIAPI
api = XUIAPI()
print(api.login())
"
```

## Добавление нового VPN-сервера

1. Установить 3X-UI на новый сервер
2. Создать inbound: VLESS + Reality (или XHTTP)
3. Добавить запись в `servers.json` (см. структуру выше)
4. Установить `"enabled": true`
5. Запустить синхронизацию:
   ```bash
   python3 sync_clients_to_servers.py
   ```
6. Проверить через бота: `/status` или команда проверки серверов

## Subscription URL сервер (sub_app.py)

```bash
# Запуск отдельного HTTP-сервера для subscription URL
# Клиент Clash/v2rayNG подписывается на: https://sub.example.com/sub/{xui_sub_id}
# sub_app.py отдаёт base64-encoded список VLESS-ссылок всех активных серверов

nohup python3 sub_app.py >> sub.log 2>&1 &
# Слушает на порту SUB_LISTEN_PORT (по умолчанию 8888)
# Проксировать через nginx на публичный домен
```

## Рабочий процесс

При запросах о боте следуй этому порядку:

1. **Диагностика**: прочитай логи, проверь статус процесса и .env
2. **Исправление**: минимальные изменения, не трогай то что работает
3. **Тест**: запусти python3 напрямую для проверки ошибок
4. **Deploy**: обнови код, перезапусти, запусти sync
5. **Верификация**: проверь что бот отвечает, клиенты созданы в панели

## Итоговое сообщение

В конце работы сообщи пользователю:
- Что было изменено и почему
- Статус бота (запущен / ошибка)
- Статус серверов (какие enabled)
- Команды для мониторинга:
  ```
  tail -f /root/MVP-SWAGA-NEW/bot.log
  journalctl -u swaga-bot -f
  python3 sync_clients_to_servers.py
  ```
