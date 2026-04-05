# CLAUDE.md — Правила и архитектура SWAGA VPN Bot

## ⛔ ЗАПРЕЩЕНО КАТЕГОРИЧЕСКИ

### Git на продакшен-сервере
- **НИКОГДА** не выполнять `git reset --hard` на продакшене
- **НИКОГДА** не выполнять `git checkout -- .` на продакшене
- **НИКОГДА** не выполнять `git clean -f` на продакшене
- **НИКОГДА** не пушить напрямую в `master` или `main`
- **НИКОГДА** не делать `git push --force` без явного разрешения

### Файлы
- **НИКОГДА** не перезаписывать `.env` на сервере — там реальные токены
- **НИКОГДА** не удалять файлы на продакшене без бэкапа
- **НИКОГДА** не изменять `bot.py`, `config.py`, `database.py` без проверки что они восстановимы

---

## 🏗️ АРХИТЕКТУРА ПРОЕКТА

### Продакшен (работает на сервере)

Сервер запускает **старый monolithic стек** — не `src/`:

| Файл | Роль |
|------|------|
| `bot.py` | Главный бот `@Swaga_vpnbot` (aiogram 2.x) |
| `sub_app.py` | HTTP-сервер подписок (aiohttp, порт 8888) |
| `support_bot.py` | Бот поддержки `@swagasupport_bot` (aiogram 2.x) |
| `config.py` | Конфигурация (токены, параметры) |
| `database.py` | SQLite `vpn_bot.db` |
| `servers.py` | Управление серверами |
| `servers.json` | Конфигурация VPN-серверов |
| `keyboards.py` | Клавиатуры Telegram |
| `payment.py` | Платежи (Telegram Stars и др.) |
| `xui_api.py` | API 3X-UI панелей |
| `yookassa_payment.py` | YooKassa интеграция |
| `backup.py` | Бэкапы |
| `utils.py` | Утилиты |
| `.env` | **РЕАЛЬНЫЕ ТОКЕНЫ** — не трогать! |

### Новая архитектура `src/` (НЕ используется на продакшене)

Директория `src/` содержит рефакторинг на aiogram 3.x + PostgreSQL + SQLAlchemy.
**На сервере НЕ запущена.** Изменения в `src/` не влияют на продакшен.

---

## 🤖 БОТЫ

### @Swaga_vpnbot (основной)
- Файл: `bot.py` (на сервере, не в git)
- Сервис: `systemctl status vpnbot`
- Возможности: покупка подписок, профиль, /keygen (admin), /broadcast

### @swagasupport_bot (поддержка)
- Файл: `support_bot.py`
- Сервис: `systemctl status swaga-support`
- Возможности: 7 тем поддержки, FSM для обращений, пересылка админу
- Медиа: `media/support_logo.png`, `media/instruction.mp4`

---

## 🌐 СЕРВЕР ПОДПИСОК (sub_app.py)

- Порт: **8888**
- Домен: `sub.swaga.su` (nginx proxy → 8888)
- Маршруты:
  - `/sub/<sub_id>` — VLESS-конфиг для импорта в приложение
  - `/connect/<sub_id>` — Страница с кнопками подключения (3 вкладки)

### Вкладки страницы /connect/:
1. **Happ Plus** — копирование ссылки в буфер, ручной импорт через "+"
2. **V2RayTun** — прямой deeplink `v2raytun://install-sub?url=...`
3. **Hiddify** — прямой deeplink `hiddify://import/...`

---

## 🌍 АКТИВНЫЕ VPN-СЕРВЕРЫ

| Сервер | ID | Статус |
|--------|----|--------|
| Франция | fr1 | ✅ активен |
| США 1 | us1 | ✅ активен |
| США 2 | us2 | ✅ активен |
| Великобритания | uk1 | ✅ активен |
| Финляндия | fi1 | ❌ удалён |
| Германия | de1 | ❌ удалён |
| Латвия | lv1 | ❌ удалён |

- Протокол: **VLESS-Reality** через 3X-UI панели
- Конфиг: `servers.json` (ключи: `xui_host`, `xui_port`, `xui_web_path`, `xui_username`, `xui_password`, `inbound_id`, `flow`)

---

## 🎁 ГИВЭВЕЙ И /keygen

### giveaway_sqlite.py
- Создаёт аккаунты с fake telegram_id ≥ `9_000_000_000`
- Читает `servers.json`, регистрирует клиентов через 3X-UI API
- `GIVEAWAY_PLANS = [("7d", 7, 3)]` — 3 аккаунта × 7 дней
- Вывод: `sub_url` и `connect_url` для каждого аккаунта

### /keygen DAYS (admin команда в bot.py)
- Применяется через `patch_keygen.py` (патчит `bot.py` на сервере)
- Поддерживаемые периоды: 7, 30, 90, 365 дней
- Создаёт гивэвей-пользователя, подписку в SQLite, синхронизирует на все серверы
- Отвечает ссылками `sub_url` и `connect_url`

---

## 🔧 PATCH-СКРИПТЫ

Поскольку `bot.py` и `sub_app.py` существуют **только на сервере** (не в git):

| Скрипт | Что патчит | Что добавляет |
|--------|-----------|---------------|
| `patch_keygen.py` | `bot.py` | /keygen DAYS handler |
| `patch_happ.py` | `sub_app.py` | /connect/ страница с 3 вкладками |

Запуск на сервере:
```bash
cd /root/MVP-SWAGA-NEW
python3 patch_keygen.py
python3 patch_happ.py
systemctl restart vpnbot
```

---

## ✅ КАК ПРАВИЛЬНО ОБНОВЛЯТЬ КОД НА СЕРВЕРЕ

```bash
# 1. Сделать бэкап .env ПЕРЕД любыми git-операциями
cp .env .env.backup

# 2. Использовать fetch + merge (НЕ reset --hard)
git fetch origin <ветка>
git merge origin/<ветка>

# 3. Если merge конфликт — решать вручную, не затирать
git status
# разрешить конфликты, затем:
git add .
git commit -m "merge: resolve conflicts"

# 4. После обновления — перезапустить сервис
systemctl restart vpnbot
systemctl restart swaga-support
journalctl -u vpnbot -f
```

---

## 🚑 КАК ВОССТАНОВИТЬ ФАЙЛЫ ПОСЛЕ ОШИБКИ

```bash
# Найти нужный коммит
git reflog
git log --oneline --all -- имя_файла.py

# Восстановить один файл
git show <ХЕШ>:имя_файла.py > имя_файла.py

# Восстановить несколько файлов
for f in bot.py config.py database.py; do
  git show <ХЕШ>:$f > $f && echo "✅ $f"
done

# Восстановить состояние до reset --hard
git show ORIG_HEAD:имя_файла.py > имя_файла.py
```

---

## 📋 ПЕРЕД ЛЮБЫМ ДЕСТРУКТИВНЫМ ДЕЙСТВИЕМ

1. Спросить пользователя: **"Это затронет продакшен — подтверждаешь?"**
2. Сделать бэкап: `cp .env .env.backup && cp bot.py bot.py.backup`
3. Объяснить что именно будет удалено/перезаписано
4. Только после явного подтверждения — выполнять

---

## 🔑 ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (.env)

| Переменная | Описание |
|-----------|---------|
| `BOT_TOKEN` | Токен основного бота |
| `SUPPORT_BOT_TOKEN` | Токен бота поддержки |
| `ADMIN_CHAT_ID` | Telegram ID администратора |
| `ADMIN_IDS` | Список ID админов (через запятую) |
| `BOT_USERNAME` | Username основного бота (без @) |
| `DATABASE_PATH` | Путь к SQLite БД (`./vpn_bot.db`) |
| `SERVERS_JSON` | Путь к `servers.json` |
| `WEBHOOK_BASE_URL` | Базовый URL сервера (напр. `https://sub.swaga.su`) |
| `SUB_BASE_URL` | URL для ссылок на подписки (`/sub/`) |

---

## 📱 ПРИЛОЖЕНИЯ ДЛЯ КЛИЕНТОВ

| Приложение | iOS | Android | Windows |
|-----------|-----|---------|---------|
| V2RayTun | [App Store](https://apps.apple.com/app/v2raytun/id6476628951) | [Play Store](https://play.google.com/store/apps/details?id=com.v2raytun.android) | — |
| Happ Plus | [App Store](https://apps.apple.com/app/id6504287215) | [Play Store](https://play.google.com/store/apps/details?id=com.happproxy) | — |
| Hiddify | [App Store](https://apps.apple.com/app/hiddify-proxy-vpn/id6596777532) | [Play Store](https://play.google.com/store/apps/details?id=app.hiddify.com) | — |
| V2RayN | — | — | [GitHub](https://github.com/2dust/v2rayn/releases) |

---

## 🛠️ ИНФРАСТРУКТУРА

- **ОС**: Ubuntu на VPS, без Docker
- **Venv**: `/root/MVP-SWAGA-NEW/venv/`
- **nginx**: проксирует `sub.swaga.su` → `localhost:8888`
- **Systemd сервисы**:
  - `vpnbot.service` — основной бот
  - `swaga-support.service` — бот поддержки
  - `swaga-sub.service` — сервер подписок (sub_app.py)
- **БД**: SQLite `vpn_bot.db` (продакшен), PostgreSQL (новая архитектура, не используется)
- **VPN панели**: 3X-UI на каждом сервере
