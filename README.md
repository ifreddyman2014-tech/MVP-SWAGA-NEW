# SWAGA VPN Bot

Telegram-бот для автоматической продажи и управления VPN-доступом через панель [3X-UI](https://github.com/MHSanaei/3x-ui) (Xray / VLESS).

## Возможности

- **Тарифные планы** — пробный (7 дней, бесплатно), 1 мес. (130 ₽), 3 мес. (350 ₽), 1 год (800 ₽)
- **Автоматическое создание VPN-клиентов** через 3X-UI API
- **Быстрое подключение** — deep link `v2raytun://` для мобильных приложений
- **Личный кабинет** — статус подписки, VLESS-конфиг, кнопка быстрого подключения
- **Пробный период** — одноразовый trial с контролем через БД
- **Оплата** — заглушка YooKassa (готова к интеграции с реальным API)
- **Автоматика** — ежедневная проверка подписок, напоминания за 3 дня, удаление истёкших клиентов
- **Бэкапы** — ежедневное копирование БД в 03:00 UTC, ротация 30 дней
- **Админ-команды** — `/reset_me` для сброса trial и удаления VPN-конфига

## Архитектура

```
.
├── bot.py              # Точка входа: хендлеры, коллбэки, scheduler
├── config.py           # Загрузка переменных окружения и констант
├── database.py         # Async SQLite (aiosqlite) — users, subscriptions, transactions
├── xui_api.py          # HTTP-клиент для 3X-UI Panel API
├── payment.py          # Заглушка платёжной системы YooKassa
├── backup.py           # Бэкап / восстановление БД
├── keyboards.py        # Reply- и Inline-клавиатуры
├── utils.py            # UUID, форматирование дат, сборка VLESS-ссылки
├── requirements.txt    # Python-зависимости
├── .env.example        # Шаблон переменных окружения
├── Dockerfile          # Образ контейнера
├── docker-compose.yml  # Оркестрация сервисов
└── vpn-bot.service     # Unit-файл systemd
```

## Стек

| Компонент      | Технология                |
|----------------|---------------------------|
| Бот-фреймворк  | aiogram 2.25 (polling)    |
| База данных    | SQLite (aiosqlite)        |
| VPN-панель     | 3X-UI (MHSanaei fork)     |
| Протокол       | VLESS + TLS               |
| HTTP-клиент    | requests                  |
| Оплата         | YooKassa (stub)           |
| Python         | 3.11+                     |

## Быстрый старт

### 1. Клонирование

```bash
git clone https://github.com/ifreddyman2014-tech/SWAGA-NEW.git
cd SWAGA-NEW
```

### 2. Настройка окружения

```bash
cp .env.example .env
nano .env
```

Заполните `.env` реальными значениями:

| Переменная     | Описание                                     |
|----------------|----------------------------------------------|
| `BOT_TOKEN`    | Токен Telegram-бота от @BotFather            |
| `ADMIN_IDS`    | Telegram ID администраторов (через запятую)   |
| `XUI_HOST`     | Адрес панели 3X-UI                           |
| `XUI_PORT`     | Порт панели (по умолчанию `443`)             |
| `XUI_WEB_PATH` | Веб-путь панели (если настроен)              |
| `XUI_USER`     | Логин панели 3X-UI                           |
| `XUI_PASS`     | Пароль панели 3X-UI                          |
| `INBOUND_ID`   | ID inbound в 3X-UI                           |
| `YOOKASSA_ID`  | ID магазина YooKassa                         |
| `YOOKASSA_KEY` | Секретный ключ YooKassa                      |
| `DB_PATH`      | Путь к файлу БД (по умолчанию `vpn_bot.db`) |
| `BACKUP_DIR`   | Директория бэкапов (по умолчанию `backups`)  |

### 3. Запуск — локально

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

### 4. Запуск — Docker

```bash
docker compose up -d

# Логи
docker compose logs -f vpn-bot
```

### 5. Запуск — systemd

```bash
sudo cp vpn-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-bot

# Статус
sudo systemctl status vpn-bot

# Логи
sudo journalctl -u vpn-bot -f
```

## Команды бота

| Команда / Кнопка              | Действие                                      |
|-------------------------------|-----------------------------------------------|
| `/start`                      | Регистрация + главное меню                    |
| `Получить доступ`             | Выбор тарифного плана                         |
| `Инструкция`                  | Как подключиться (V2RayTun, v2rayN)           |
| `Личный кабинет`              | Статус подписки, VLESS-конфиг, Quick Connect  |
| `/reset_me` _(только админ)_  | Сброс trial + удаление VPN-конфига            |

## Формат VLESS-ссылки

```
vless://{uuid}@{host}:{port}?type=tcp&security=tls&sni={host}&host={host}&path={path}#VPN-SWAGA
```

Значения по умолчанию: `host=yandex.ru`, `port=443`, `path=/adv`.

## Фоновые задачи (Scheduler)

| Время (UTC) | Задача                                                             |
|-------------|--------------------------------------------------------------------|
| 00:00       | Проверка подписок: напоминания (за 3 дня), деактивация истёкших    |
| 03:00       | Бэкап БД в `backups/backup_YYYYMMDD_HHMMSS.db`                    |

## Бэкапы

- **Автоматические** — каждый день в 03:00 UTC
- **Ротация** — хранятся последние 30 дней, старые удаляются
- **Восстановление:**

```python
from backup import restore_backup
restore_backup("20260131_030000")  # формат: YYYYMMDD_HHMMSS
```

## База данных

SQLite с тремя таблицами:

```
users
├── user_id        (PK, Telegram ID)
├── username
├── reg_date
├── trial_used     (0/1)
└── current_server (default 1)

subscriptions
├── sub_id         (PK, autoincrement)
├── user_id        (FK → users)
├── plan           (trial / 1m / 3m / 1y)
├── start_date
├── end_date
├── is_active      (0/1)
└── vless_uuid

transactions
├── id             (PK, autoincrement)
├── user_id        (FK → users)
├── amount
├── status
└── timestamp
```

## Настройка 3X-UI

1. Установите [3X-UI](https://github.com/MHSanaei/3x-ui) на сервер
2. Создайте inbound с протоколом **VLESS + TLS**
3. Запишите `INBOUND_ID` (виден в URL панели при редактировании inbound)
4. Укажите данные панели в `.env`

Бот автоматически создаёт и удаляет клиентов через API панели.

## Интеграция YooKassa

Сейчас используется заглушка (`payment.py`). Для подключения реальных платежей:

1. Зарегистрируйтесь в [YooKassa](https://yookassa.ru/)
2. Получите `SHOP_ID` и `SECRET_KEY`
3. Реализуйте создание платежа и обработку webhook в `payment.py`
4. Укажите `YOOKASSA_ID` и `YOOKASSA_KEY` в `.env`

## Устранение неполадок

**Бот не отвечает:**
```bash
# Docker
docker compose logs -f vpn-bot

# systemd
sudo journalctl -u vpn-bot -f
```

**3X-UI не подключается:**
- Проверьте `XUI_HOST` и `XUI_PORT`
- Убедитесь, что панель доступна: `curl -k https://{XUI_HOST}:{XUI_PORT}/login`
- Проверьте логин/пароль

**Подписка не создаётся:**
- Проверьте `INBOUND_ID` — он должен совпадать с ID в панели
- Убедитесь, что inbound активен и поддерживает VLESS

## Лицензия

MIT
