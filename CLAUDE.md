# CLAUDE.md — Правила работы с репозиторием SWAGA

---

## 📋 ПРАВИЛО: ВЕДЕНИЕ CHANGELOG

После **каждой сессии** с изменениями кода — добавлять запись в раздел `## 📝 CHANGELOG` в конце этого файла.

**Формат записи:**
```
### ДД.ММ.ГГГГ — Краткое описание сессии

**файл.py:**
- что изменено и зачем

**Другой файл:**
- что изменено
```

**Правила:**
- Дата в формате ДД.ММ.ГГГГ
- Указывать конкретные файлы и что в них изменилось
- Фиксировать исправленные баги, новые фичи, изменённые ссылки/константы
- Новые записи добавлять **сверху** (последнее — первым)
- Не удалять старые записи

---

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
- **НИКОГДА** не изменять `src/main.py`, `src/config.py`, `src/database/models.py` без проверки восстановимости

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

# 4. После обновления — перезапустить оба сервиса
systemctl restart vpnbot && systemctl restart swaga-support
journalctl -u vpnbot -f
```

---

## 🔧 АРХИТЕКТУРА СЕРВЕРА

- **ОС**: Ubuntu на VPS, без Docker
- **Venv**: `/root/MVP-SWAGA-NEW/venv/`
- **БД**: SQLite (`vpn_bot.db`), aiosqlite async
- **Конфиг серверов**: `servers.json` в корне проекта

---

## 🤖 ДВА БОТА ПРОЕКТА

| Параметр | Основной бот | Саппорт-бот |
|---|---|---|
| Файл запуска | `bot.py` | `support_bot.py` |
| systemd-юнит | `vpnbot` | `swaga-support` |
| aiogram | 2.x | 2.x |
| Токен | `BOT_TOKEN` | `SUPPORT_BOT_TOKEN` |
| Username | `Swaga_vpnbot` | `SWAGASupport_bot` |
| Порт | 8888 (aiohttp sub_app) | нет (polling) |

### Управление сервисами

```bash
# Основной бот
systemctl restart vpnbot
journalctl -u vpnbot -f

# Саппорт-бот
systemctl restart swaga-support
journalctl -u swaga-support -f

# Статус обоих
systemctl status vpnbot swaga-support
```

---

## 🏗️ АРХИТЕКТУРА ОСНОВНОГО БОТА

```
bot.py (aiogram 2.x polling)
├── sub_app.py (aiohttp, 127.0.0.1:8888) — раздача подписок и вебхуки
├── servers.py / servers.json             — мультисервер, health-check, балансировка
├── database.py                           — SQLite через aiosqlite
└── фоновые задачи (asyncio):
    ├── _scheduler_expiration_check       — деактивация истёкших подписок
    ├── _scheduler_reminders              — напоминания за 24ч и в день истечения
    ├── _scheduler_backup                 — ежедневный бэкап БД в ./backups/
    └── _scheduler_server_failover        — автомиграция при падении сервера
```

Nginx проксирует `sub.swaga-vpn.ru:443` → `127.0.0.1:8888`

### HTTP-эндпоинты (sub_app.py)

| URL | Метод | Назначение |
|---|---|---|
| `/health` | GET | Проверка работоспособности |
| `/sub/{sub_id}` | GET | Раздача конфигов VPN-клиентам (base64 VLESS) |
| `/connect/{sub_id}` | GET | Веб-страница пользователя с инструкцией |
| `/webhook/yookassa` | POST | Приём платёжных уведомлений |

### Ключевые файлы (НЕ УДАЛЯТЬ)

```
bot.py              — основной бот, все хэндлеры, scheduler'ы
sub_app.py          — aiohttp сервер подписок + YooKassa webhook
support_bot.py      — саппорт-бот (aiogram 2.x)
database.py         — все функции работы с SQLite (aiosqlite)
config.py           — настройки из .env
servers.py          — ServerManager: загрузка, health-check, балансировка
servers.json        — конфиг VPN-серверов
xui_api.py          — HTTP-клиент для 3X-UI API
yookassa_payment.py — создание платежей и парсинг webhook YooKassa
keyboards.py        — Inline-клавиатуры
utils.py            — generate_uuid, build_vless_link, format_date
backup.py           — backup_now() для ежедневного бэкапа БД
vpn_bot.db          — база данных SQLite (РЕАЛЬНЫЕ ДАННЫЕ)
.env                — токены и секреты (НЕ ТРОГАТЬ)
```

**Папка `src/` — НЕИСПОЛЬЗУЕМАЯ старая архитектура** (aiogram 3.x + PostgreSQL). Не запускается, не трогать.

---

## 🗄️ СХЕМА БАЗЫ ДАННЫХ (SQLite: vpn_bot.db)

```
users         (user_id, username, reg_date, trial_used, referred_by, referral_bonus_given, compensation_claimed)
subscriptions (sub_id, user_id, plan, start_date, end_date, is_active, vless_uuid, xui_sub_id, reminder_sent, server_id, xui_email)
payments      (id, payment_id, user_id, amount, plan_key, server_id, status, created_at, paid_at)
transactions  (id, user_id, amount, status, timestamp)
promo_codes   (id, code, discount_percent, max_uses, used_count, is_active, created_at)
promo_uses    (id, promo_id, user_id, used_at)
```

- **`vless_uuid`** — UUID клиента в 3X-UI (один на все серверы)
- **`xui_sub_id`** — subId для subscription URL в 3X-UI
- **`server_id`** — ID основного сервера (fr1, us1 и т.д.)
- **`reminder_sent`** — JSON-строка с кодами отправленных напоминаний

### Типы подписок (plan)

| Значение | Описание |
|---|---|
| `trial` | Пробный период (7 дней) |
| `1m` | 1 месяц (130 руб) |
| `3m` | 3 месяца (350 руб) |
| `1y` | 1 год (900 руб) |
| `giveaway_7d` | Гивей 7 дней |
| `giveaway_365d` | Гивей 365 дней |

---

## 📡 VPN-СЕРВЕРЫ И 3X-UI

- **Протокол:** VLESS-Reality (TCP + xtls-rprx-vision)
- **Конфиг:** `servers.json` — список серверов с параметрами подключения
- **Балансировка:** `ServerManager.get_best_server()` — по приоритету и `current_users`
- `current_users` заполняется из БД при каждом `load_config()` — не хранится между перезапусками

### Активные серверы

| Сервер | IP | VPN-порт | Статус |
|---|---|---|---|
| Франция (fr1) | 194.59.31.100 | 54232 | ✅ активен |
| США 1 (us1) | 80.76.49.140 | 35887 | ✅ активен |
| Великобритания (uk1) | 163.5.210.147 | 36158 | ✅ активен |
| США 2 (us2) | 31.57.38.104 | 52670 | ✅ активен |

### Добавление нового сервера

Добавить запись в `servers.json` и перезапустить бота:

```json
{
  "id": "de2",
  "name": "Германия 2",
  "host": "1.2.3.4",
  "xui_host": "1.2.3.4",
  "xui_port": 2053,
  "xui_web_path": "/secretpath",
  "xui_username": "admin",
  "xui_password": "pass",
  "vpn_port": 443,
  "inbound_id": 1,
  "max_users": 150,
  "priority": 10,
  "enabled": true,
  "location": "DE",
  "transport": "tcp",
  "flow": "xtls-rprx-vision",
  "reality_pbk": "...",
  "reality_sid": "...",
  "reality_sni": "www.example.com",
  "reality_fp": "chrome"
}
```

---

## 💳 ПЛАТЁЖНАЯ СИСТЕМА (YooKassa)

```
Пользователь нажал "Купить"
→ bot создаёт Payment(status=pending) в БД
→ bot создаёт платёж через YooKassa API → получает payment_url
→ пользователь оплачивает в браузере
→ YooKassa POST /webhook/yookassa (event: payment.succeeded)
→ payment_service.handle_webhook() активирует Subscription + создаёт Key на всех серверах
→ бот уведомляет пользователя
```

### Тарифы

| Тариф | plan_key | Цена |
|---|---|---|
| 1 месяц | `1m` | 130 руб |
| 3 месяца | `3m` | 350 руб |
| 1 год | `1y` | 900 руб |

---

## 🔔 НАПОМИНАНИЯ О ПОДПИСКЕ

Фоновая задача `subscription_reminder_loop`, проверяет каждые 15 минут:

| Событие | Действие |
|---|---|
| До истечения < 24ч, флаг `notified_24h=False` | Отправить напоминание, поставить флаг |
| До истечения < конец дня, флаг `notified_0h=False` | Отправить напоминание, поставить флаг |
| Подписка истекла, флаг `expired_handled=False` | Деактивировать, уведомить пользователя |

---

## 👮 КОМАНДЫ АДМИНИСТРАТОРА

| Команда | Описание |
|---|---|
| `/giveaccess USER_ID DAYS` | Создать или продлить подписку пользователю |
| `/user_extend USER_ID DAYS` | Продлить существующую подписку |
| `/user_info USER_ID` | Инфо о пользователе и подписке |
| `/servers` | Статус всех серверов (health check) |
| `/broadcast ТЕКСТ` | Рассылка всем активным подписчикам |
| `/keygen DAYS` | Создать гивей-ключ без привязки к пользователю. Допустимые значения: 7, 30, 90, 365 |
| `/promo_add КОД СКИДКА МАКС` | Создать промокод (скидка в %, макс. использований) |
| `/promo_list` | Список всех промокодов |
| `/promo_del КОД` | Деактивировать промокод |
| `/capacity` | Статистика загрузки серверов |

---

## 🤝 САППОРТ-БОТ (aiogram 2.x)

- Меню: лого отправляется отдельным `answer_photo`, затем текст — отдельным `answer`
- **НЕЛЬЗЯ** делать `edit_text` на сообщении-фото — будет `BadRequest: There is no text in the message to edit`
- Кнопка "Назад" всегда делает `edit_text` на текущем сообщении

```
Пользователь → "Связаться с техподдержкой"
→ FSM: SupportState.waiting_message
→ пользователь пишет/прикрепляет скриншот
→ бот пересылает в ADMIN_CHAT_ID с шапкой (имя, username, ID)
→ оператор отвечает reply
→ бот парсит ID из шапки и отправляет ответ пользователю
```

---

## 🔑 ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (.env)

```env
BOT_TOKEN=                    # токен @Swaga_vpnbot
BOT_USERNAME=Swaga_vpnbot
ADMIN_IDS=                    # через запятую
SUPPORT_URL=https://t.me/SWAGASupport_bot

SUPPORT_BOT_TOKEN=            # токен @SWAGASupport_bot

DATABASE_PATH=./vpn_bot.db
BACKUP_PATH=./backups

YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_WEBHOOK_SECRET=      # опционально

SUB_BASE_URL=https://sub.swaga-vpn.ru/sub/
SUB_LISTEN_PORT=8888

# VPN дефолтный сервер (fallback если servers.json пустой)
VPN_HOST=
VPN_PORT=443
REALITY_PUBLIC_KEY=
REALITY_SHORT_ID=
REALITY_SNI=

TRIAL_DAYS=7
LOG_LEVEL=INFO
```

---

## 🚑 КАК ВОССТАНОВИТЬ ФАЙЛЫ ПОСЛЕ ОШИБКИ

```bash
# Найти нужный коммит
git reflog
git log --oneline --all -- bot.py

# Восстановить один файл
git show <ХЕШ>:bot.py > bot.py

# Восстановить несколько файлов
for f in bot.py sub_app.py database.py; do
  git show <ХЕШ>:$f > $f && echo "✅ $f"
done

# Восстановить состояние до reset --hard
git show ORIG_HEAD:bot.py > bot.py
```

---

## 📋 ПЕРЕД ЛЮБЫМ ДЕСТРУКТИВНЫМ ДЕЙСТВИЕМ

1. Спросить пользователя: **"Это затронет продакшен — подтверждаешь?"**
2. Сделать бэкап: `cp .env .env.backup`
3. Объяснить что именно будет удалено/перезаписано
4. Только после явного подтверждения — выполнять

---

## 📊 СОСТОЯНИЕ СЕРВЕРОВ (актуально на 05.04.2026)

### Активные VPN-серверы

| Сервер | IP | VPN-порт | Панель 3X-UI | SSH-доступ |
|---|---|---|---|---|
| Франция (fr1) | `194.59.31.100` | 54232 | `:4444/[panel-path]` | root — credentials stored locally |
| США 1 (us1) | `80.76.49.140` | 35887 | `:61753/[panel-path]` | root — credentials stored locally |
| Великобритания (uk1) | `163.5.210.147` | 36158 | `:3226/[panel-path]` | root — credentials stored locally |
| США 2 (us2) | `31.57.38.104` | 52670 | `:448/[panel-path]` | root — credentials stored locally |

**Важно:** fr1 (194.59.31.100) — это одновременно бот-сервер и VPN-сервер. На нём крутятся `vpnbot`, `swaga-support` и xray.

**Важно:** us1 (80.76.49.140) — на сервере есть сторонние сервисы (`youtube-search`, `profkom`, `pvs_system`), потребляют ~300 MB RAM дополнительно.

### Нагрузка на 05.04.2026

| Сервер | Соединений VPN | CPU xray | RAM xray | Load avg |
|---|---|---|---|---|
| fr1 | 377 | 3.1% | ~100 MB | 0.33 |
| us1 | 98 | 0.4% | ~50 MB | 0.03 |
| uk1 | 78 | 0.1% | ~43 MB | 0.00 |
| us2 | 48 | 0.4% | ~50 MB | 0.13 |

**Резерв мощности:** ~3–5% от максимума. Можно расти в 20–30 раз без апгрейда серверов.

### Подписчики на 05.04.2026

| Тип | Кол-во |
|---|---|
| Всего активных подписок | 71 |
| Платящих (1m + 3m + 1y) | 38 |
| Пробный период | 27 |
| Giveaway | 6 |

Клиентов в 3X-UI панелях (включая старые/удалённые): fr1=211, us1=200, uk1=133, us2=138.
Реально когда-либо использовали VPN (>1MB трафика): fr1=92, us1=37, uk1=23, us2=22.

---

## 🔍 КАК БЫСТРО ПРОВЕРИТЬ СОСТОЯНИЕ

### Подписчики и деньги
```bash
# Активные подписки по типу
sqlite3 /root/MVP-SWAGA-NEW/vpn_bot.db "
SELECT plan, COUNT(*) FROM subscriptions
WHERE is_active=1 AND end_date >= date('now')
GROUP BY plan ORDER BY COUNT(*) DESC;"

# Только платящие
sqlite3 /root/MVP-SWAGA-NEW/vpn_bot.db "
SELECT COUNT(*) FROM subscriptions
WHERE is_active=1 AND end_date >= date('now') AND plan IN ('1m','3m','1y');"

# Распределение по серверам
sqlite3 /root/MVP-SWAGA-NEW/vpn_bot.db "
SELECT server_id, COUNT(*) FROM subscriptions
WHERE is_active=1 AND end_date >= date('now')
GROUP BY server_id ORDER BY COUNT(*) DESC;"
```

### Сервисы бота
```bash
systemctl status vpnbot swaga-support --no-pager
journalctl -u vpnbot -n 20 --no-pager
```

### Реальная нагрузка на VPN-серверах (соединения + CPU)
```bash
# Credentials are stored locally outside git. Do not commit secrets.
# Use: sshpass -p '[SSH_PASS]' ssh root@<IP> "<command>"

# fr1
sshpass -p '[SSH_PASS]' ssh root@194.59.31.100 \
  "uptime && ss -tn state established | grep :54232 | wc -l && ps aux | grep xray | grep -v grep | awk '{print \"CPU:\"\$3\"% MEM:\"\$4\"%\"}'"

# us1
sshpass -p '[SSH_PASS]' ssh root@80.76.49.140 \
  "uptime && ss -tn state established | grep :35887 | wc -l && ps aux | grep xray | grep -v grep | awk '{print \"CPU:\"\$3\"% MEM:\"\$4\"%\"}'"

# uk1
sshpass -p '[SSH_PASS]' ssh root@163.5.210.147 \
  "uptime && ss -tn state established | grep :36158 | wc -l && ps aux | grep xray | grep -v grep | awk '{print \"CPU:\"\$3\"% MEM:\"\$4\"%\"}'"

# us2
sshpass -p '[SSH_PASS]' ssh root@31.57.38.104 \
  "uptime && ss -tn state established | grep :52670 | wc -l && ps aux | grep xray | grep -v grep | awk '{print \"CPU:\"\$3\"% MEM:\"\$4\"%\"}'"
```

### Все серверы одной командой
```bash
# Credentials are stored locally outside git. Do not commit secrets.
# Fill in [SSH_PASS] values from your local credentials store before running.
for S in "fr1|194.59.31.100|[SSH_PASS]|54232" "us1|80.76.49.140|[SSH_PASS]|35887" "uk1|163.5.210.147|[SSH_PASS]|36158" "us2|31.57.38.104|[SSH_PASS]|52670"; do
  N=$(echo $S|cut -d'|' -f1); IP=$(echo $S|cut -d'|' -f2)
  PASS=$(echo $S|cut -d'|' -f3); PORT=$(echo $S|cut -d'|' -f4)
  echo -n "$N: "
  sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 root@$IP \
    "echo -n 'conn='; ss -tn state established | grep :$PORT | wc -l | tr -d '\n'; echo -n ' cpu='; ps aux | grep xray | grep -v grep | awk '{print \$3\"%\"}" 2>/dev/null
done
```

---

## 📝 CHANGELOG

### 20.09.2026 — H5-MINI Renewal Attribution

**database.py:**
- Added `renew_source TEXT DEFAULT NULL` column to payments table; ALTER TABLE migration for existing DBs.
- `create_payment()` accepts optional `renew_source` kwarg; stored at creation, not updated later.

**keyboards.py:**
- `plans_kb()` accepts `renew_source=None`; encodes source in callback_data as `plan_{key}:{renew_source}` when provided. Without source, callbacks unchanged.

**bot.py:**
- `_renew_click()`: passes attribution source to `plans_kb(renew_source=source)`.
- `cb_plan_selected()`: parses `plan_{key}:{renew_source}` format; threads renew_source through to `create_payment`.
- `_create_subscription_on_server()`: accepts and stores `renew_source`.
- `handle_payment_success()`: reads `renew_source` from payment record (safe `.get()`); logs `event=payment_renew_success source=...`; failure never blocks fulfillment.

**tests/test_h5_attribution.py (NEW):**
- 19 tests A–L: source stored at creation (A–F), source belongs to payment not user (G–H), webhook preserves source (I), idempotent duplicate (J), attribution failure safe (K), H3/H4 regression (L). All GREEN.

**scripts/renewal_report.py (NEW):**
- Read-only report: historical baseline ([-14d, +7d] window, pre-H3), post-H3 attribution by renew_source, pending first-cohort.

**Historical baseline:** 20 eligible renewal cycles pre-H3, 5/20 = 25% renewed. Post-H3: 1 payment (unattributed, direct purchase). First attributed cohort starts from next renewal click.

**Deploy:** commit 498298b, vpnbot restarted 16:45Z. 267/267 tests. Column 11 = renew_source confirmed in production DB.

### 20.09.2026 — H3 Renewals/Retention

**Scope:** reminders, cabinet CTA, dedup reset. INFRA FREEZE respected — zero infra changes.

**keyboards.py:**
- Added `renew_cta_kb(source="")` — single-button [Продлить подписку] keyboard.
  `source` → `callback_data=renew_{source}` (or `get_access` if empty).
- `quick_connect_kb`: added [Продлить подписку] button with `callback_data=renew_cabinet`.

**bot.py:**
- `from keyboards import renew_cta_kb` added to imports.
- `_scheduler_expiration_check`: removed duplicate 3-day reminder block (`list_expiring` call).
  Expired notification now includes `reply_markup=renew_cta_kb("expired")`.
- `_scheduler_reminders`: all 3 stages (3d/1d/3h) now include `reply_markup=renew_cta_kb(…)`.
  Copy updated to Russian retention-focused messages.
- Added `_renew_click(callback, source)` — shared handler: logs `event=renew_click source=… user=…`,
  shows tariff-selection screen via `plans_kb` (respects trial_used + promo discount).
- Added 5 source-tagged handlers: `cb_renew_72h`, `cb_renew_24h`, `cb_renew_3h`,
  `cb_renew_expired`, `cb_renew_cabinet` — each calls `_renew_click`.

**database.py:**
- `begin_fulfillment` renewal UPDATE: added `reminder_sent = ''` reset.
  After a paid renewal changes end_date, the new expiry window starts a fresh reminder cycle.

**tests/test_h3_renewals.py (NEW, 23 tests):**
- A–D: each reminder stage sends inline renewal CTA.
- E–E3: renew_cta_kb structure + source handlers existence.
- F–G: cabinet CTA for active and expired users.
- H–I: expiration check no longer calls list_expiring; get_subs_for_reminder/mark_reminder_sent API.
- J–K: renewal semantics (is_renewal param, ✅ + format_date in confirmation).
- L: reminder copy doesn't contain "платн".
- M–M3: provisioning/xui_api/servers untouched.
- N1–N3: expiry-aware dedup — begin_fulfillment resets reminder_sent; NOT LIKE guard; routing.
- N4–N5b: migration safety — legacy flags preserved; scheduler never clears reminder_sent.

**Deploy:** commit 40d7526. vpnbot restarted 1 time at 16:01Z. 219/225 tests pass
(6 pre-existing failures: test_h2 M/O + test_xui_ensure_client 32/33/34/51 — unrelated to H3).

**Retention baseline (pre-H3):**
- Unique paid active: 31 (1y=14, 3m=9, 1m=8)
- 90-day renewal opportunities: 41
- 30-day renewal rate: 1/3 (33%) — 3 paid expired, 1 renewed
- Expiring ≤3d: 3 subs (2 paid: sub 350/expired, sub 359/2026-09-21; 1 trial)
- Lapsed paid (no active sub, expired last 30d): 2

### 20.09.2026 — H2 Confirmed-Profile Delivery

**Invariant:** NEVER advertise a VPN profile unless access is confirmed on the panel.

**provisioning.py (NEW):**
- Central resolver: `resolve_available_profiles(candidate_servers, uuid, email, sub_id, expiry_ms) → ProvisioningResult`.
- `ProvisioningResult(available_servers, failed_servers)` — only confirmed servers reach the caller.
- Protected server guard (us2, us2-ws) before any I/O; per-server exception isolation.
- `server_sync_client()` — consolidated idempotent sync (WS→ws_manager, non-standard→ensure_client_uk1, standard→ensure_client with email alias).
- `panel_email / PANEL_EMAIL_SUFFIXES` — email alias scheme (us1-xhttp → _i3).

**xui_api.py:**
- No-shrink invariant in `ensure_client` and `ensure_client_uk1`: if panel already holds a later expiry, return `ALREADY_OK` (never shorten the subscription).

**sub_app.py (/sub and /connect):**
- Call `resolve_available_profiles` at request time; build VLESS links only from `available_servers`.
- Uses `asyncio.get_running_loop()` (not deprecated `get_event_loop()`).
- VLESS config built directly from confirmed server objects (not secondary `get_server_config()` lookup).

**bot.py:**
- Module-level `from provisioning import resolve_available_profiles` (patchable in tests).
- Module-level `from servers import server_manager` (patchable in tests).
- `handle_payment_success` renewal path: replaces primary sync + `_sync_client_to_other_servers` with single `resolve_available_profiles` call.
- `handle_payment_success` new-sub path: same. Zero confirmed → problem message sent (`⚠️`, NOT `✅`), payment NOT marked fulfilled (startup sync will retry).
- `_create_subscription_on_server` trial path: replaces `_server_add_client` + `_sync_client_to_other_servers` with `resolve_available_profiles`.

**tests/test_h2_confirmed_profiles.py (NEW, 29 tests):**
- A–E: resolver contract and protected server exclusion.
- F–J: server_sync_client routing (alias, uk1-fork, WS, exception isolation).
- K–L: /sub and /connect output contains only confirmed servers.
- M–N: payment partial (mark fulfilled) vs zero (NOT fulfilled, problem message, no "✅").
- O–P: trial and renewal resolver integration.
- Q–R: no-shrink invariant and idempotency.

**Deploy:** commit db62ae3, vpnbot restarted 09:51Z. 202/202 tests. Production smoke: /sub → 7 confirmed servers, all ALREADY_OK (idempotent).

### 19.09.2026 — H1-F1 Read-First XUI Provisioning (Standard Panels)

**Root causes fixed:**
- RC-1: `_NOT_FOUND_MARKERS` в `add_or_update_client` не включал "empty client ID" →
  sync на FR/US1/US1-xhttp молча падал для новых UUID (updateClient возвращал ошибку,
  fallback на addClient не срабатывал).
- RC-2: UK1 3X-UI форк возвращает HTTP 404 на `updateClient` даже для существующих UUID →
  несовместимый маршрут; UK1/UK1-xhttp теперь помечены `xui_standard: false` и пропускаются.

**xui_api.py:**
- Добавлен `EnsureResult(Enum)`: CREATED, UPDATED, ALREADY_OK, CONFLICT, FAILED.
- Добавлен `get_inbound_clients(inbound_id)`: читает список клиентов из панели.
  Возвращает `list | None`. None ≠ пустой список: None = панель недоступна или несовместима.
  Возвращает None если settings — dict (UK1-формат), чтобы не допустить запись.
- Добавлен `ensure_client(...)`: read-first идемпотентное начисление.
  1. Читает список → FAILED если None. 2. UUID найден → updateClient → UPDATED/FAILED.
  3. UUID не найден, email занят другим UUID → CONFLICT. 4. Оба отсутствуют → addClient → CREATED/FAILED.
  Не использует error-string parsing. Не допускает слепой addClient при сетевом сбое.

**servers.py:**
- Добавлено поле `xui_standard: bool = True` в VPNServer.
  False для панелей с несовместимым API (UK1 форк).

**bot.py (`_server_sync_client`):**
- Убран вызов `add_or_update_client`. Заменён на `ensure_client`.
- Добавлен guard `if not getattr(server, "xui_standard", True): return False`
  после WS-ветки — для UK1/UK1-xhttp sync деферится без IO.
- Возвращает True для CREATED/UPDATED/ALREADY_OK, False для CONFLICT/FAILED.

**servers.json (untracked):**
- `uk1` и `uk1-xhttp`: добавлен `"xui_standard": false`.
- `us2`, `us2-ws`: НЕ ТРОНУТЫ (H0 защита).

**tests/test_xui_ensure_client.py (новый файл, 30 тестов):**
- GROUP 1: get_inbound_clients — 6 тестов (happy path, пустой список, HTTP error, dict-settings, success=false, ID not found).
- GROUP 2: ensure_client — 8 тестов (CREATED, UPDATED, CONFLICT, FAILED×3, incident payload, ALREADY_OK).
- GROUP 3: EnsureResult enum существует и является Enum.
- GROUP 4: xui_standard поле в VPNServer и servers.json (uk1/uk1-xhttp false, fr1/us1 true).
- GROUP 5: _server_sync_client routing (xui_standard=False, us2, us2-ws, CREATED/UPDATED/CONFLICT/FAILED).
- GROUP 6: H0 инварианты сохранены после H1-F1.

**tests/test_fulfillment_sync_reliability.py:**
- `_xui_mock`: добавлен `ensure_client.return_value` (EnsureResult.UPDATED/FAILED по `aou_returns`).
  Необходимо так как _server_sync_client теперь вызывает ensure_client, а не add_or_update_client.

**Деплой:** commit 396233d, vpnbot restarted 07:03Z. 121/121 тестов. Worktree: /tmp/swaga-h1f1-ensure-client-20260919.

### 18.09.2026 — H0 Protected Server Containment

**servers.py:**
- `get_best_server()`: добавлен фильтр `s.id not in PROTECTED_SERVER_IDS` в основной пул и fallback-пул. До фикса us2 (priority=10, 0% load) выигрывал сортировку и назначался новым пользователям.

**bot.py:**
- Удалён локальный дубликат `_PROTECTED_SERVER_IDS = {"us2", "us2-ws"}` (был на строке 95).
- Добавлен `from servers import PROTECTED_SERVER_IDS` — единственный источник истины.
- `_server_add_client()`: добавлен guard в самом начале функции — `if server.id in PROTECTED_SERVER_IDS: return False`. Предотвращает любые обращения к XUIAPI или ws_manager для защищённых серверов.
- Все 5 упоминаний `_PROTECTED_SERVER_IDS` переименованы в `PROTECTED_SERVER_IDS`.

**sub_app.py:**
- Добавлен `PROTECTED_SERVER_IDS` в импорт из servers.
- `handle_subscription (/sub/)` и `handle_connect (/connect/)`: оба фильтра `enabled_servers` дополнены условием `s.id not in PROTECTED_SERVER_IDS`. Защищённые серверы больше не включаются в конфиги, выдаваемые пользователям.

**tests/test_protected_server_policy.py (НОВЫЙ ФАЙЛ):**
- 16 TDD-тестов (RED → GREEN): selection (A-D), provision guard (E-H), output filter (I-K), policy regression (L-O).
- Итого suite: 91/91 тестов.

**Деплой:** commit 391fd09, vpnbot restarted 1 раз в 16:15Z. DB до/после: 102 активных подписки, без изменений.

### 18.09.2026 — NGINX/PERIMETER HARDENING (Run D) — INFRA FREEZE

**nginx.conf:**
- `server_tokens off` — версия nginx скрыта из заголовков ответов.
- `ssl_protocols TLSv1.2 TLSv1.3` — убраны TLSv1.0, TLSv1.1 (были включены; fr.swaga-vpn.ru уже использовал TLS 1.2+).

**sites-enabled/swaga-vpn.conf, sites-available/tono-business.conf:**
- `X-Content-Type-Options: nosniff` и `Referrer-Policy: no-referrer-when-downgrade` добавлены в web-блоки (swaga-vpn.ru, business.swaga-vpn.ru). Не добавлены в WS/subscription блоки.

**Backups:** `/etc/nginx/*.pre_rund_20260918T070427Z`, `/root/nginx_full_config_pre_rund_20260918T070427Z.txt` (600).

**Перimeter:** Port 2096 (x-ui admin) — защищён nftables SWAGA_XUI2096_V4 на FR/US1/UK1. Изменений firewall не потребовалось.

**Reload:** `systemctl reload nginx` в 20260918T070706Z. `nginx -t` PASS. nginx active.

**SWAGA INFRA FREEZE активен с 18.09.2026.** Дальнейшие инфра-изменения только при: инциденте, эксплуатируемой уязвимости, проблеме с надёжностью, масштабировании, новом продуктовом требовании.

### 18.09.2026 — FR SSH Hardening (Run C.2)

**Проблема:** FR допускал password authentication. UK1/US1 уже hardened в Run C (17.09.2026).

**/etc/ssh/sshd_config.d/10-swaga-hardening.conf (НОВЫЙ ФАЙЛ):**
- `10-` prefix — takes priority before `60-cloudimg-settings.conf` (PasswordAuthentication yes).
- Эффективно: PasswordAuthentication no, KbdInteractiveAuthentication no, PubkeyAuthentication yes, PermitRootLogin prohibit-password.
- systemctl reload ssh (НЕ restart). Текущая сессия сохранена.
- Password auth rejection verified (BatchMode=yes, PreferredAuthentications=password → Permission denied (publickey)).
- Backup: /etc/ssh/sshd_config.pre_swaga_hardening_20260918T064902Z, /etc/ssh/sshd_config.d/60-cloudimg-settings.conf.pre_swaga_hardening_20260918T064902Z.

**Operator pre-hardening evidence:** FR_KEY_OK verified from Windows workstation before hardening.
**Post-hardening external check:** FR_KEY_OK_AFTER VERIFIED — confirmed from Windows workstation 18.09.2026.

### 17.09.2026 — WS_MANAGER HOST-IDENTITY FIX (fix/ws-manager-host-identity, коммит 1600ae7)

**Проблема:** После XUI tunnel cutover (xui_host=127.0.0.1 для UK1/US1) ws_manager._is_local()
маршрутизировал все WS файловые операции на локальный FR filesystem вместо физического удалённого хоста.
Поле xui_host выполняло двойную роль: endpoint управления XUI и физический хост для ws_manager SSH.

**ws_manager.py:**
- Добавлена константа `KNOWN_HOSTS_PATH = "/root/.ssh/swaga_ws_manager_known_hosts"` — выделенный known_hosts для ключей автоматизации.
- Добавлена `_ssh_key(host, key_path, command, input_data, timeout)` — SSH через ed25519 ключ:
  StrictHostKeyChecking=yes, BatchMode=yes, UserKnownHostsFile=dedicated, без sshpass.
  Передаёт stdin для команды записи (base64 pipe).
- `_read_config`, `_write_config`, `_reload` — добавлен параметр `ssh_key=""`:
  если задан → key-auth path, иначе → legacy sshpass (backward compat).
- Команда записи через key-auth: `base64 -d > {path}` через stdin вместо inline python3.
  Совместима с forced-command wrapper.
- `add_client`, `delete_client` — добавлены параметры `ssh_key=""` и `fail_closed=False`.
  `fail_closed=True`: remote host без ключа → return False, без fallback на sshpass.
  Legacy path (no key, no fail_closed) сохранён для dormant записей (us2-ws).

**servers.py:**
- Добавлены поля `ws_host: str = ""` и `ws_ssh_key: str = ""` в VPNServer.
  `ws_host` = физический хост xray-ws (отдельно от xui_host = management tunnel endpoint).

**bot.py:**
- `_server_add_client`, `_server_delete_client`, `_server_sync_client`:
  ws_host = `server.ws_host or server.xui_host` — передаётся в ws_manager вместо xui_host.
  ssh_key = `server.ws_ssh_key` — передаётся напрямую.

**servers.json (не git-tracked):**
- fr1-ws: добавлены `ws_host=127.0.0.1`, `ws_ssh_key=""` (локальный, без ключа).
- us1-ws: добавлены `ws_host=80.76.49.140`, `ws_ssh_key=/root/.ssh/swaga_us1_ws_manager_ed25519`.
- uk1: добавлены `ws_host=163.5.210.147`, `ws_ssh_key=/root/.ssh/swaga_uk1_ws_manager_ed25519`.
- us2-ws: НЕ ТРОНУТ (защищённый сервер).

**tests/test_ws_manager_host_identity.py (НОВЫЙ ФАЙЛ, 12 тестов):**
- TEST 1–4: routing корректно использует ws_host, не xui_host.
- TEST 5: legacy compatibility (sshpass path для старых записей).
- TEST 6: key-auth команда содержит -i, BatchMode=yes, StrictHostKeyChecking=yes, dedicated known_hosts.
- TEST 7–9: US1/UK1 операции не трогают FR filesystem и наоборот.
- TEST 10: fail_closed=True без ключа → False, без fallback на sshpass.
- TEST 11: nonzero SSH exit → False.
- TEST 12: legacy entry без новых полей → sshpass path.

**Инфраструктура (FR/US1/UK1):**
- Ключи: `/root/.ssh/swaga_us1_ws_manager_ed25519`, `/root/.ssh/swaga_uk1_ws_manager_ed25519` (ed25519, 600).
- Fingerprints: US1=SHA256:ABAAzPt1AZa8Ai8845MgMxXHg+oclLuHbgFZhAk9blA, UK1=SHA256:rQLz9GhCTPlmS6cVDSdLyvwzXb0oLdg0GCdqmOEh4jU.
- Wrapper: `/usr/local/sbin/swaga-ws-manager-remote` (root:root 700) на US1 и UK1.
  Разрешает ровно: cat config, base64-d write, systemctl restart xray-ws. Остальное — denied.
- authorized_keys: restricted entry (no-agent-forwarding, no-port-forwarding, no-X11-forwarding, no-pty, no-user-rc, command=wrapper) добавлен на US1 и UK1.
  Backup: `authorized_keys.pre_ws_manager_20260917` на обоих хостах.
- Known_hosts: `/root/.ssh/swaga_ws_manager_known_hosts` (600), 6 записей (ED25519/RSA/ECDSA × 2 хоста).

**Результаты проверки:**
- 75/75 тестов PASS (12 новых + 63 baseline).
- Controlled routing verification: fr1-ws→FR only ✓, us1-ws→US1 only ✓, uk1→UK1 only ✓.
- Хэши FR/US1/UK1 после теста = хэшам до теста (cleanup чистый).
- vpnbot NRestarts=1 (один перезапуск для деплоя).
- DB: active=101, paid=31, pending_fulfillment=0 (без мутаций).

### 17.09.2026 — Изоляция тестов от продакшн БД (fix/test-db-isolation, коммит 941d7d4)

**tests/test_payment_logic.py:**
- Исправлен баг import-order: `db.DB_PATH = _TEMP_DB.name` явно выставляется ПОСЛЕ
  `import database as db`, чтобы перезаписать кэшированный путь к продакшн-БД.
  Ранее `_config.DB_PATH = temp` не обновляло `database.DB_PATH`, если модуль уже
  был в `sys.modules` (собран раньше другим тест-файлом — в алфавитном порядке).
  Результат: все 18 тестов молча писали в продакшн БД.
- Добавлена `_assert_db_isolation()`: tripwire перед первой записью в `setUpClass`.
  Поднимает `RuntimeError` если `database.DB_PATH` = продакшн, или `config.DB_PATH`
  = продакшн, или два пути расходятся (split-brain).
- Добавлены константы `_PRODUCTION_DB_PATH` и комментарий о причине порядка импортов.

**tests/test_fulfillment_sync_reliability.py:**
- Та же fix-паттерн: `_db.DB_PATH = _TEMP_DB_PATH` после `import database as _db`.
- Все `aiosqlite.connect(_TEMP_DB_PATH)` в хелперах заменены на `aiosqlite.connect(_db.DB_PATH)`,
  чтобы хелперы всегда работали с той же БД, что и `_db.create_user / create_subscription`.

**tests/test_payment_db_isolation.py (НОВЫЙ ФАЙЛ):**
- Регрессионный тест: импортирует `database` на уровне модуля (алфавит: 'd' < 'p'),
  гарантируя, что `database` окажется в `sys.modules` ДО сбора `test_payment_logic.py`.
- test_01: `database.DB_PATH != production` (FAIL без фикса, PASS после).
- test_02: `database.DB_PATH == config.DB_PATH` (split-brain = FAIL).
- test_03: `_assert_db_isolation` существует и бросает `RuntimeError` при split-brain.
- test_04: tripwire бросает при `database.DB_PATH == production`.

**Состояние тестов:** 63/63 passed (было 59 до добавления 4 новых тестов).

**Инцидент — повторное загрязнение продакшн БД (17.09.2026 10:39 UTC):**
- При демонстрации RED-состояния (запуск тестов ДО фикса) `test_payment_logic.py`
  записал данные в продакшн (db.DB_PATH указывал на vpn_bot.db).
- Добавлено: +10 подписок (дубли для uid 100001-110015), +8 платежей (pay_dup_001,
  pay_concurrent_001, pay_bf_*, pay_accum_a/b).
- Итого synthetic данных в продакшн: users=10, subs=19, payments=8.
- Удаление НЕ выполнялось (см. правило "DO NOT cleanup synthetic users").
- Фикс исключает повторение: tripwire остановит тесты при следующей попытке.

**Ветка:** `fix/test-db-isolation`, от `dashboard-v1` (41c31b4)
**Продакшн не перезапускался. Бизнес-логика не изменялась.**

### 16.09.2026 — Атомарное начисление доступа + тесты + подготовка к выпуску

#### ⚠️ ВЛИЯНИЕ НА US2 — ТРЕБУЕТ ОТДЕЛЬНОГО СОГЛАСОВАНИЯ

Синхронизация клиентов на US2 изменилась с предыдущей сессии (15.09.2026):
- **Было:** `addClient` при каждом sync → создавались дубликаты в панели US2.
- **Стало:** `add_or_update_client` (update-first, idempotent) → дубликаты устранены.
- US2 не перезапускался, конфиг не менялся, VPN не прерывался.
- Изменение затрагивает следующие пути: продление подписки (`handle_payment_success`),
  синхронизацию на все серверы (`_sync_client_to_other_servers`), стартовую синхронизацию
  незавершённых начислений (`_startup_sync_pending_fulfillments`).
- **Перед деплоем** требуется явное согласование этого изменения для US2.

**database.py:**
- Добавлена колонка `fulfillment_status TEXT DEFAULT NULL` в таблицу payments.
  Значения: NULL (старые записи), 'pending' (DB consistent, sync панели не завершён),
  'fulfilled' (полностью завершено).
- Добавлена `begin_fulfillment()`: атомарная запись через `BEGIN IMMEDIATE` —
  одна транзакция помечает платёж как succeeded, записывает target_end_date,
  обновляет/создаёт подписку и ставит fulfillment_status='pending'.
  Сетевые вызовы (3X-UI) выполняются строго после commit.
  Возврат: ('first'|'sync_pending'|'already_fulfilled'|'not_found', target_end, sub_info).
  Два платежа одного пользователя сериализуются — каждый читает уже обновлённую end_date.
- Добавлена `mark_payment_fulfilled(payment_id)`: переводит fulfillment_status в 'fulfilled'.
- Добавлена `get_pending_fulfillments()`: возвращает платежи с fulfillment_status='pending'
  для стартовой синхронизации. Реализует no-shrink: sync_end = max(target_end, sub.end_date).
- `_read_sub_info_on_conn()`: внутренний хелпер для чтения sub_info внутри транзакции.
- Все try/except в блоках ALTER TABLE миграций: `Exception` → `sqlite3.OperationalError`.
- fulfillment_status добавлена в CREATE TABLE payments (для новых установок).

**sub_app.py:**
- Удалена `_recover_if_needed()` — заменена атомарным механизмом begin_fulfillment.
- Webhook handler упрощён: всегда вызывает callback с `paid_at`. Idempotency и crash recovery
  обеспечиваются внутри callback через begin_fulfillment.

**bot.py:**
- `handle_payment_success` принимает `paid_at: str = ""`.
- Renewal path: `set_payment_target_end + extend_subscription_to_date` заменены вызовом
  `begin_fulfillment(is_renewal=True, existing_uuid=...)`.
- New-sub path: UUID/sub_id/email генерируются до begin_fulfillment.
  `set_payment_target_end + deactivate_user_subs + create_subscription` заменены вызовом
  `begin_fulfillment(is_renewal=False, new_uuid=...)`. Сетевые вызовы (add_or_update_client)
  — после commit. На сетевой ошибке fulfillment_status='pending' — стартовая синхронизация
  повторит.
- Добавлена `_startup_sync_pending_fulfillments()`: вызывается в on_startup после init_db.
  Находит pending fulfillments и повторяет sync панелей без пересчёта дней.
- Добавлен вызов `mark_payment_fulfilled(payment_id)` после успешной синхронизации.

**backup.py:**
- `backup_now()` переведён с `shutil.copy2` на `sqlite3.backup()` (online backup API):
  корректно работает при открытых WAL-транзакциях, гарантирует консистентный снапшот.
- Добавлена проверка `PRAGMA integrity_check` на бэкапе.
- `restore_backup()` аналогично переведён на `sqlite3.backup()`.
- Удалён неиспользуемый import `shutil`.

**scripts/reconcile_expiry.py:**
- Исправлена загрузка серверов: `servers.json` имеет формат `{"servers": [...]}`,
  скрипт теперь корректно извлекает список через `.get("servers", data)`.

**tests/test_payment_logic.py:**
- Тесты 11-13 (проверка удалённой `_recover_if_needed`) заменены на тесты для begin_fulfillment:
  - test_11: begin_fulfillment renewal 'first' path — atomicity, fulfillment_status='pending'
  - test_12: begin_fulfillment new sub без существующей подписки — sub создаётся в DB
  - test_13: concurrent BEGIN IMMEDIATE — только один возвращает 'first'
  - test_14: два платежа одного пользователя — дни накапливаются без перезаписи
  - test_15: 'sync_pending' + no-shrink — expiry_ms = max(target_end, sub.end_date)
- Итого: 15/15 passed.

**Git / безопасность:**
- `git rm --cached .env` — .env убран из отслеживания, рабочий файл сохранён.
- .gitignore уже содержал правила для .env и *.db.
- ВАЖНО: .env присутствует в git-истории (коммиты b79dd51, 8c1267b) и был запушен
  на ветку origin/claude/refactor-telegram-vpn-bot-COHgs. Токены скомпрометированы.
  Ротация токенов — отдельное согласование. История не переписана (без явного разрешения).

#### Dry-run результаты

**migration_fix_plan.py:**
- Активных trial-подписок: 14
- К исправлению (plan: trial → платный): 9
- Неоднозначных (несколько plan_key в периоде, пропущены): 3 → ручной разбор
- Без платежей (легитимный trial/giveaway): 2
- Примечание: `paid_at >= sub.start_date` — необходимое, но не достаточное условие.
  Неоднозначные случаи не исправляются автоматически.

**reconcile_expiry.py:**
- Серверов проверено: 4 (fr1, us1, us1-xhttp, uk1-xhttp; us2/ws исключены)
- Активных подписок в DB: 101
- Панель отстаёт от DB: 19 → можно --apply (поштучно, с подтверждением)
- Панель опережает DB: 0 → ничего применять нельзя
- Не найдено в панели: 1 (us1, план 3m)
- uk1-xhttp: ошибка парсинга настроек inbound (JSON вместо строки в settings) → SKIP

#### Расположение и состояние перед деплоем

- Ветка: `dashboard-v1`, HEAD: `e8cbc51` + незакоммиченные изменения
- Изменённые файлы: `database.py`, `sub_app.py`, `bot.py`, `backup.py`,
  `scripts/reconcile_expiry.py`, `tests/test_payment_logic.py`, `CLAUDE.md`
- Удалено из git-индекса: `.env` (требует включения в коммит как `git rm --cached .env`)
- Бэкап DB: `backups/vpn_bot_audit_fix_20260915_214332.db` (старый, из прошлой сессии)
- Перед коммитом: сделать новый бэкап через `backup_now()` (теперь использует SQLite API)
- Продакшн не перезапускался. Изменения применяются только после явного согласования.

### 15.09.2026 — Аудит + фикс платёжных багов (Duplicate email, plan='trial', идемпотентность)

**xui_api.py:**
- Добавлена `_parse_api_response(resp)`: безопасный парсинг ответов панели, логирует HTTP status при non-JSON, не раскрывает тело (CSRF/HTML).
- Добавлена `_client_payload()`: DRY-сборка payload для add/update.
- Добавлена `add_or_update_client()`: идемпотентная синхронизация — сначала `updateClient/{uuid}`, при ответе «not found» → `addClient`. Non-JSON ответы (HTML, 502) не вызывают fallback на addClient.
- Все вызовы `resp.json()` заменены на `_parse_api_response(resp)`.

**database.py:**
- `extend_subscription_to_date()`: добавлен опциональный параметр `plan=None`. При передаче — обновляет и поле `plan` (нужно при переходе trial→платный тариф).
- `update_payment_status()`: добавлен атомарный guard `WHERE status != 'succeeded'` для статуса succeeded — повторный webhook не переписывает уже обработанный платёж.

**bot.py:**
- Добавлена `_server_sync_client()`: идемпотентная синхронизация одного клиента на один сервер. WS → ws_manager (уже идемпотентен), XUI → `add_or_update_client`.
- `_sync_client_to_other_servers()`: переписана на `_server_sync_client`, добавлен параметр `is_renewal` для контекстного логирования.
- Все 11 вызовов `_sync_client_to_other_servers` обновлены: переданы флаги `is_renewal=True` (продление/реферал) и `is_renewal=False` (новая подписка).
- Два вызова `extend_subscription_to_date()` в путях оплаты обновлены: теперь передают `plan=plan_key`, что исправляет баг plan='trial' после оплаты.

**scripts/reconcile_expiry.py (НОВЫЙ ФАЙЛ):**
- Dry-run инструмент: сравнивает `end_date` в БД с `expiryTime` в 3X-UI панелях.
- Пропускает us2, us2-ws. WS-серверы пропускаются (expiry только в БД).
- Режим `--apply UUID`: точечное исправление одного клиента с подтверждением.
- Выход: 0=норма, 1=нашлись расхождения, 2=ошибка.

**scripts/migration_fix_plan.py (НОВЫЙ ФАЙЛ):**
- Dry-run миграция: находит активные подписки с `plan='trial'` при наличии succeeded-платежей.
- Предлагает исправить `plan` на тариф из истории платежей. Неоднозначные случаи (несколько plan_key) — помечаются AMBIGUOUS, не исправляются.
- Режим `--apply`: транзакционное обновление с pre-check (still active, still trial).

**tests/test_payment_logic.py (НОВЫЙ ФАЙЛ):**
- 9 тестов: trial→платный, продление, дубль-webhook, extend без plan, update-first, fallback на add, non-JSON не триггерит add, таймаут, US2 исключён из sync.
- Все тесты: 9/9 passed (in-memory SQLite, mock HTTP).

**AUDIT-2026-09-15.md (НОВЫЙ ФАЙЛ):**
- Диагностический отчёт по 8 направлениям: MRR, Duplicate email, non-JSON UK1, серверы, SSL, периметр, UK1 состояние, git.
- Резервная копия БД: `backups/vpn_bot_audit_fix_20260915_214332.db` (WAL-safe).

### 25.08.2026 — Metrics v0.2 + Dashboard V1

**metrics.py (НОВЫЙ ФАЙЛ, ветка dashboard-v1):**
- Полная реализация метрик v0.2. `PRAGMA query_only = ON` — никаких записей в БД.
- `calc_data_integrity()`: убран ложный алерт "succeeded_payment→no active sub" (нормальный отток); split `active_sub_without_payment` на `active_free_without_payment` (норма) и `paid_plan_without_payment` (ERROR).
- Новая `calc_customer_status()`: total_real / never_paid / active_free / ever_paid / active_paid / inactive_paid.
- Новая `calc_buyer_metrics()`: Buyer Conversion, Active Buyer Rate, Repeat Buyer Rate, High-Frequency Buyers (3+/4+/5+), Cash ARPPU Historical.
- Новая `calc_payment_entitlement()`: confirmed / suspicious (renewals) / unverifiable.
- Новая `simulate_pricing()`: чистая функция, --simulate-pricing CLI arg.
- Верифицированные значения на 25.08.2026: active_paid=30, MRR=2650.83₽, ARPPU=92.19₽, ever_paid=50, total_real=126.

**web_app.py (НОВЫЙ ФАЙЛ в индексе, ветка dashboard-v1):**
- `DB_PATH` добавлен в `from config import`.
- Добавлен маршрут `GET /admin/metrics` — HTML dashboard (same auth ?token= как /admin).
- Добавлен маршрут `GET /api/admin/metrics` — JSON.
- Добавлен маршрут `GET /api/admin/metrics/simulate` — AJAX pricing simulator.
- `_mdash_cache` / `_get_dashboard_metrics()`: 60-секундный кэш метрик.
- `_render_metrics_dashboard()`: сервер-сайд рендер страницы (~25KB HTML).
- Разделы дашборда: header (READ ONLY badge), KPI grid ×2, Growth row, Customer Status bars, Active Plan Mix, Revenue, Road to MRR, Purchase Mix, Payment Entitlement, Data Quality, Pricing Simulator (AJAX).
- Без изменений: bot.py, database.py, sub_app.py, servers.py, servers.json, xui_api.py, ws_manager.py, yookassa_payment.py, nginx, systemd, 3X-UI.

**Безопасность:**
- Ветка: `dashboard-v1` (от 67dca45)
- Бэкап БД: `vpn_bot.db.backup.dashboard_v1_20260825_165750`
- us2 не тронут. VPN серверы не тронуты. Продакшн не перезапускался. БД не записывалась.

### 08.08.2026 — Аудит платёжной системы, фикс flow в VLESS-ссылке

**Результаты аудита (всё работает корректно):**
- Webhook идемпотентность ✅ (повторный webhook игнорируется если status уже succeeded)
- Nginx bypass для /webhook/yookassa ✅ (исправлен 08.07.2026)
- Промокоды: `uses_count` — имя колонки совпадает с кодом ✅
- Expiry синхронизируется на все серверы через `_sync_client_to_other_servers` ✅
- Реферальный бонус обновляет 3X-UI на всех серверах ✅
- Просроченных активных подписок: 0 (шедулер работает) ✅
- 55 pending платежей в БД — все легитимно заброшенные (пользователи не завершили оплату)

**bot.py:**
- Исправлен баг: в `build_vless_link` не передавался параметр `flow=srv.flow` в двух местах:
  `_create_subscription_on_server` (trial/платные при первом открытии) и `handle_payment_success` (вебхук).
  Для TCP/Reality серверов (fr1, us1, us2) отсутствие `flow=xtls-rprx-vision` в inline VLESS-ссылке
  в сообщении об оплате делало её нерабочей. Ссылка-подписка `/sub/` работала корректно.

### 21.07.2026 (продолжение 2) — us1-xhttp: новый xhttp/Reality сервер США 1 на порту 2053

**us1-xhttp (80.76.49.140:2053):**
- Новый x-ui inbound id=3, порт 2053, протокол xhttp/Reality
- Reality ключи (новая пара, не shared с us1 TCP):
  - Public key: `o1_K4y3D6-9uJl5rkcGF2MYm9_T1RVOq5cTV4o_IECs`
  - Private key: `2PkibiUAROnF0r4HuHyS0_Stke3Veqft7TU0DYoNJ0Y` (в x-ui DB)
  - Short ID: `4e26051c3f7fca`, SNI: `www.microsoft.com`, mode: `packet-up`
- 319 существующих пользователей us1 скопированы в inbound 3 (без flow)
- servers.json: добавлен `us1-xhttp` (priority=1, transport=xhttp, vpn_port=2053, inbound_id=3)
- Бот перезапущен — все 9 серверов активны

**Итого серверов теперь 9:**
fr1, fr1-ws, us1, us1-ws, us1-xhttp, uk1, uk1-xhttp, us2, us2-ws

---

### 21.07.2026 (продолжение) — Фикс nginx: fr.swaga-vpn.ru не маршрутизировался в nginx

**Проблема:** fr1-ws WS-подключение не работало.

**Причина 1:** `fr.swaga-vpn.ru` отсутствовал в stream map (`/etc/nginx/nginx.conf`). Трафик
шёл в `default → 127.0.0.1:54232` (xray Reality), который отвечал AkamaiGHost 400.
Фикс: добавлена строка `fr.swaga-vpn.ru 127.0.0.1:4443;` в stream map.

**Причина 2:** Server block для `fr.swaga-vpn.ru` был добавлен в `/etc/nginx/sites-available/swaga-vpn.conf`
(не используется nginx), а не в `/etc/nginx/sites-enabled/swaga-vpn.conf` (активный файл).
В sites-enabled все server blocks используют `listen 127.0.0.1:4443 ssl http2` (не 443) —
потому что stream block проксирует TCP с порта 443 на 4443.

**Исправлено:**
- `/etc/nginx/nginx.conf`: stream map дополнен `fr.swaga-vpn.ru 127.0.0.1:4443;`
- `/etc/nginx/sites-enabled/swaga-vpn.conf`: добавлен server block fr.swaga-vpn.ru с `listen 127.0.0.1:4443 ssl http2`
- nginx перезагружен, fr.swaga-vpn.ru теперь отдаёт Cloudflare Origin Certificate ✅
- bot перезапущен — все 8 серверов загружены

**Статус DNS (нужно добавить в Cloudflare Dashboard):**
- `fr.swaga-vpn.ru` → 194.59.31.100 (Proxied) ❌ НЕ ДОБАВЛЕН
- `us1.swaga-vpn.ru` → 80.76.49.140 (Proxied) ❌ НЕ ДОБАВЛЕН
- `us2.swaga-vpn.ru` → 31.57.38.104 (Proxied) ❌ НЕ ДОБАВЛЕН

---

### 21.07.2026 — 8 вариантов серверов: WS+TLS для fr1/us1/us2 + uk1-xhttp восстановлен

**Цель:** 4 физических сервера × 2 транспорта = 8 VLESS-ссылок в подписке.

**Инфраструктура новых WS-серверов:**

| Сервер | IP | Nginx WS порт | xray-ws порт | WS path |
|---|---|---|---|---|
| fr1-ws | 194.59.31.100 | 443 (доп. server block) | 8080 (localhost) | /swaga-fr-ws |
| us1-ws | 80.76.49.140 | 8443 (новый nginx config) | 8081 (localhost) | /swaga-us1-ws |
| us2-ws | 31.57.38.104 | 8443 (заменён gRPC config) | 8080 (localhost) | /swaga-us2-ws |

- Cloudflare Origin Cert (`*.swaga-vpn.ru`) скопирован с uk1 на fr1, us1, us2 → `/etc/ssl/cloudflare/`
- systemd xray-ws.service создан на всех трёх серверах, xray-ws активен
- 99 существующих пользователей мигрированы в новые xray-ws конфиги одним скриптом

**ws_manager.py:**
- Добавлена поддержка localhost: если `host` = `127.0.0.1` / `localhost` / `::1`,
  читает/пишет файлы напрямую (без SSH) и перезапускает сервис через `subprocess`
- fr1-ws использует `xui_host: "127.0.0.1"` → локальные операции без SSH-пароля

**servers.py:**
- Добавлено поле `reality_spx: str = "/"` в VPNServer (ранее не было в dataclass)
- Добавлено в `save_config()` для сохранения

**servers.json — 8 записей:**
- `fr1` (TCP/Reality, port 54232, priority 10) — без изменений
- `fr1-ws` (WS+TLS, fr.swaga-vpn.ru:443, priority 1) — НОВЫЙ
- `us1` (TCP/Reality, port 443, priority 10) — без изменений
- `us1-ws` (WS+TLS, us1.swaga-vpn.ru:8443, priority 1) — НОВЫЙ
- `uk1` (WS+TLS, uk.swaga-vpn.ru:443, priority 10) — без изменений
- `uk1-xhttp` (xHTTP/Reality, 163.5.210.147:443, priority 1) — ВОССТАНОВЛЕН из x-ui inbound 2
- `us2` (TCP/Reality, port 443, priority 10) — без изменений
- `us2-ws` (WS+TLS, us2.swaga-vpn.ru:8443, priority 1) — НОВЫЙ

WS-варианты имеют `priority: 1` → никогда не выбираются как primary при балансировке.
Reality/TCP серверы (priority 10) остаются основными для назначения новым пользователям.

**uk1-xhttp параметры (из x-ui DB):**
- pbk: `QQ4VLkJYdQ8WyJKaBxK_anw-I69nRzL2GGuhzFfkE3Q`
- sid: `a1420449606c4c`, sni: `www.microsoft.com`, mode: `packet-up`
- Трафик: клиент → 163.5.210.147:443 (nginx stream) → port 10000 (x-ui xray)

**DNS (Cloudflare) — требует ручного добавления:**
- `fr.swaga-vpn.ru` → 194.59.31.100 (Proxied)
- `us1.swaga-vpn.ru` → 80.76.49.140 (Proxied)
- `us2.swaga-vpn.ru` → 31.57.38.104 (Proxied)
- `uk.swaga-vpn.ru` → 163.5.210.147 (уже создан)

---

### 20.07.2026 — uk1 Великобритания: переход с xhttp/Reality на WS+TLS через Cloudflare CDN

**Инфраструктура uk1 (163.5.210.147):**
- Nginx stream (порт 443) маршрутизирует по SNI: `uk.swaga-vpn.ru` → 4443 (nginx HTTPS+WS proxy), остальное → 10000 (xray x-ui)
- Cloudflare Origin Certificate (`*.swaga-vpn.ru`, 15 лет RSA) в `/etc/ssl/cloudflare/`
- Standalone xray-ws сервис `/etc/systemd/system/xray-ws.service` → конфиг `/etc/xray-ws/config.json`
- xray-ws слушает на 127.0.0.1:8080, nginx проксирует WS (path: `/swaga-uk-ws`)
- DNS uk.swaga-vpn.ru → 163.5.210.147 (Cloudflare Proxied — оранжевое облако)

**ws_manager.py (НОВЫЙ ФАЙЛ):**
- SSH-based управление клиентами для standalone xray-ws: `add_client` и `delete_client`
- Читает/пишет `/etc/xray-ws/config.json` через base64-кодирование (избегает shell-escaping проблем)
- После каждого изменения: `systemctl restart xray-ws`

**servers.json (uk1):**
- `host`: `163.5.210.147` → `uk.swaga-vpn.ru` (клиенты подключаются через CF CDN)
- `transport`: `xhttp` → `ws`
- `transport_path`: `/` → `/swaga-uk-ws`
- `transport_host`: `www.microsoft.com` → `uk.swaga-vpn.ru`
- `xhttp_mode`, `reality_pbk/sid/sni/fp`: очищены (не нужны для WS)
- Добавлены `ws_ssh_password` и `ws_config_path` для SSH-управления

**servers.py:**
- Добавлены поля в VPNServer: `ws_ssh_password`, `ws_config_path`
- `save_config()` сохраняет эти поля

**utils.py:**
- `build_vless_link()`: добавлен case `transport == "ws"` → `security=tls&type=ws&path=...&host=...&sni=...` (без Reality параметров)

**sub_app.py:**
- `get_server_config()`: условие `if srv and srv.reality_pbk:` → добавлено `or srv.transport == 'ws'`, чтобы WS серверы не падали на глобальные defaults

**bot.py:**
- Новые хелперы `_server_add_client(server, ...)` и `_server_delete_client(server, ...)`:
  WS серверы → `ws_manager`, остальные → `xui_api`
- `_sync_client_to_other_servers`: переведён на `_server_add_client` (поддержка WS)
- `_delete_client_from_all_servers`: переведён на `_server_delete_client`
- `cmd_giveaccess`, `cmd_keygen`, `_create_subscription_on_server`, webhook handler: переведены на хелперы
- Failover migration и cleanup: переведены на хелперы
- Условие `if server.reality_pbk:` заменено на `if server.reality_pbk or transport == 'ws':` в 4 местах (корректная генерация VLESS ссылок для WS)
- Расширение подписки: для WS серверов `update_client` пропускается (expiry только в БД)
- Компенсация: WS-проверка добавлена

**Миграция существующих uk1 пользователей:**
- 7 активных uk1 пользователей добавлены в `/etc/xray-ws/config.json` через ws_manager
- xray-ws перезапущен, 8 клиентов активны (включая тестовый `tv6xxcnyz4-ws`)

**Формат VLESS ссылки для uk1 (WS):**
```
vless://UUID@uk.swaga-vpn.ru:443?security=tls&type=ws&path=%2Fswaga-uk-ws&host=uk.swaga-vpn.ru&sni=uk.swaga-vpn.ru#SWAGA%20UK
```

---

### 20.07.2026 — Смена IP сервера Франция (fr1): 194.59.30.107 → 194.59.31.100

**servers.json:**
- fr1 `host` и `xui_host`: `194.59.30.107` → `194.59.31.100`
- Боты перезапущены для перезагрузки конфига: `systemctl restart vpnbot swaga-support`

**tono-business.conf:**
- `server_name`: заменён старый IP `194.59.30.107` на `194.59.31.100` (оба server-блока)
- Nginx перезагружен: `systemctl reload nginx`

**CLAUDE.md:**
- Все упоминания `194.59.30.107` заменены на `194.59.31.100`

**DNS (reg.ru) — swaga.fortis-pro.ru:**
- A-запись обновлена: `194.59.30.107` → `194.59.31.100`
- Промежуточно была опечатка `194.59.30.100` (исправлена вручную)
- TTL=86400, поэтому полная propagation заняла несколько часов
- Cloudflare (1.1.1.1) и Яндекс (77.88.8.8) подтянули сразу, Google (8.8.8.8) кэшировал ~6ч

**DNS (Cloudflare) — swaga-vpn.ru, sub.swaga-vpn.ru:**
- Требуют обновления origin A-record в CF Dashboard (proxied, снаружи видны CF IP)
- ⚠️ Не обновлялись в этой сессии — сделать вручную

### 11.07.2026 — INCY в странице подключения + фикс SSL-протокола для UK

**sub_app.py:**
- Добавлен таб «🟣 INCY» в список приложений на странице /connect/{sub_id}
- Deeplink: `incy://import/{sub_url}` — автоматический импорт подписки в INCY
- INCY добавлен первым в списке рекомендаций iOS (App Store РФ) и Android (Google Play)
- Ссылки: iOS `apps.apple.com/ru/app/incy/id6756943388`, Android `play.google.com/store/apps/details?id=llc.itdev.incy`

**bot.py:**
- КРИТИЧЕСКИЙ БАГ: 7 мест игнорировали `xui_ssl: false` и всегда ставили HTTPS для внешних хостов.
  Код проверял `if server.xui_host not in ("127.0.0.1", "localhost"): protocol = "https"` — это игнорировало поле xui_ssl.
  У uk1 стоит `xui_ssl: false` (HTTP), но код пытался HTTPS → `SSLError: wrong version number`.
  Исправлено: все 7 блоков заменены на `protocol = "https" if getattr(server, "xui_ssl", True) else "http"`.

**Известная задача (требует доступа к серверу uk1):**
- 3X-UI панель на 163.5.210.147:3226 возвращает 404 на все пути, включая `/[panel-path]/`
- Web path панели изменился (вероятно, после сброса/переустановки)
- Для фикса: зайти на сервер, выполнить `sqlite3 /etc/x-ui/x-ui.db "SELECT value FROM settings WHERE key='webBasePath';"` и обновить `xui_web_path` в servers.json
- VPN (порт 443) работает — существующие пользователи подключены

### 08.07.2026 — Полный аудит: 4 бага исправлены, Karing проверен

**bot.py:**
- КРИТИЧЕСКИЙ БАГ: `_scheduler_expiration_check()` использовал глобальный `xui.delete_client()` для всех серверов.
  Это вызывало `Invalid URL 'https://:443/login'` при попытке удалить клиентов с us1/uk1/us2 в полночь.
  Исправлено: добавлена функция `_delete_client_from_all_servers(uuid, inbound_id_fallback)`,
  которая проходит по всем enabled серверам и удаляет клиента с каждого.
- `_scheduler_expiration_check()`: добавлена проверка `0 < uid < 9_000_000_000` перед отправкой
  Telegram-уведомления — пропускаем giveaway-ключи (uid > 9B) и web-пользователей (uid < 0).
  Раньше попытки отправить в несуществующие чаты генерировали warning-спам.

**servers.py:**
- `save_config()`: добавлены пропущенные поля `xui_ssl` и `flow`.
  Без них `/server_toggle` команда перезаписывала servers.json, теряя `xui_ssl=false` (uk1)
  и `flow=xtls-rprx-vision` (все серверы) — при следующем `load_config()` uk1 переходил на HTTPS,
  а все серверы теряли flow-параметр → сломанные VLESS-ссылки.

**Результаты аудита (всё работает):**
- Karing: /sub/ endpoint возвращает корректный base64 VLESS×4 (200 OK в логах) ✅
- /sub/ заголовки: subscription-userinfo, profile-update-interval, profile-title ✅
- Все 4 сервера здоровы (xray запущен, порты открыты) ✅
- fr1: порт 54232 (исправлено в предыдущей записи), VLESS-ссылки верные ✅
- uk1: порт 443, VLESS-ссылки верные ✅
- Nginx: конфиг проверен, webhook bypass работает ✅

### 08.07.2026 — Диагностика uk1, фикс XUIAPI trailing slash

**Итог диагностики uk1 (163.5.210.147):**
- VPN работает: xray слушает :443, 7 клиентов активны, expiry в норме (2027+).
- На uk1 установлен другой форк x-ui (API `/panel/api/clients/` вместо `/panel/api/inbounds/`).
  Бот не может добавлять/обновлять клиентов на uk1 — API несовместим.
  При синхронизации uk1 будет fail, но silent (try/catch).
- Реальная проблема (из лога бота): CSRF + trailing slash в xui_web_path.

**servers.json:**
- uk1 `xui_web_path`: убран trailing slash `/[panel-path]/` → `/[panel-path]`.
  Из-за trailing slash URL строился как `...//login` (двойной слеш) → 404/empty body.

**xui_api.py:**
- Добавлен метод `_url(path)` — защита от двойных слешей при построении API URL.
  `self.base_url.rstrip("/") + "/" + path.lstrip("/")`
- CSRF токен теперь сохраняется в `session.headers` (persistent) — применяется ко всем запросам сессии.
  Ранее: хранился только в локальной переменной `headers` внутри `login()`, теряясь после.

**Известная задача (не исправлено):** uk1 использует другой форк x-ui — нужно либо переустановить
стандартный 3x-ui на uk1, либо добавить поддержку нового API в xui_api.py.

### 08.07.2026 — Фикс: fr1 vpn_port=443 (неверно), исправлено на 54232

**servers.json:**
- fr1 `vpn_port`: 443 → 54232. На fr1 nginx занимает порт 443; xray VLESS-Reality слушает на 54232.
  Все VLESS-ссылки для fr1 генерировались с портом 443 → пользователи попадали в nginx, не в xray → "use of closed network connection".
- us1, uk1, us2 — vpn_port=443 корректно, xray реально слушает там.

**bot.py:** перезапущен для перезагрузки servers.json.

### 08.07.2026 — Фикс: YooKassa вебхуки блокировались nginx (403), ручная активация 6 платежей

**Причина бага:** В nginx конфиге `sub.swaga-vpn.ru` стояла глобальная проверка Cloudflare на уровне server-блока (`if ($is_cloudflare = 0) { return 403; }`). Запросы YooKassa приходят напрямую (не через Cloudflare), поэтому вебхуки получали 403. В итоге все платежи с 1 июля зависли в статусе `pending`.

**Симптом:** в nginx логах — `"POST /webhook/yookassa HTTP/2.0" 403` от YooKassa (user-agent `AHC/2.1`), каждые 3 часа.

**/etc/nginx/sites-enabled/swaga-vpn.conf:**
- Заменил `if ($is_cloudflare = 0) { return 403; }` на тройную проверку (double-if паттерн):
  путь `/webhook/*` проходит без проверки Cloudflare, все остальные пути проверяются как прежде.

**Ручная активация платежей (скрипт удалён после выполнения):**
- 5081729040 → 1m, продление до 2026-11-06
- 730405056 → 3m, новая подписка до 2026-10-06 (us1)
- 971376379 → 1m, новая подписка до 2026-08-07 (us1)
- 1857765533 → 1m, продление до 2026-08-13
- 1442375960 → 3m, продление до 2026-10-06 (plan trial→3m исправлен в БД)
- 2079986207 → 1m, новая подписка до 2026-08-07 (us1)

**Важно:** uk1 (163.5.210.147) не отвечает на логин — существующая проблема, не связанная с этим фиксом.

### 29.06.2026 — Замена сервера Великобритания + удаление gRPC

**servers.json:**
- uk1: IP заменён с `45.95.18.254` на `163.5.210.147`, порт VPN `36158`, панель `:3226/[panel-path]`, inbound_id=2, `xui_ssl=false`
- fr1: удалены поля grpc_inbound_id, grpc_service_name, grpc_domain, grpc_port

**servers.py:**
- Добавлено поле `xui_ssl: bool = True` — переключает схему http/https для 3X-UI API
- Удалены поля grpc_inbound_id/grpc_service_name/grpc_domain/grpc_port из VPNServer
- `check_server_health`: переход с `https://` hardcode на `server.xui_ssl`; добавлена поддержка CSRF-токена (обязателен в 3X-UI v3.x); добавлен `CookieJar(unsafe=True)` для работы с IP-адресами

**bot.py:**
- Все ручные `session.post(... json={"username":...})` заменены на `XUIAPI.login(username, password)` (поддерживает CSRF)
- Удалена вся логика gRPC inbound (добавление клиентов в grpc_inbound) в трёх местах: keygen, _create_subscription_on_server (trial), webhook

**xui_api.py:**
- `XUIAPI.login()` обновлён: принимает username/password, автоматически получает CSRF-токен, использует form data вместо JSON

**sub_app.py:**
- Удалён блок добавления gRPC ссылки в /sub/{sub_id}

**Новый сервер uk1 (163.5.210.147):**
- Установлен 3X-UI v3.4.1
- Создан VLESS-Reality inbound на порту 36158 (microsoft.com SNI)
- Public key: QQ4VLkJYdQ8WyJKaBxK_anw-I69nRzL2GGuhzFfkE3Q
- 7 активных пользователей перенесены в новую панель

### 04.06.2026 — gRPC транспорт: интеграция в keygen и создание подписок

**servers.py:**
- Добавлены поля в `VPNServer`: `grpc_inbound_id`, `grpc_service_name`, `grpc_domain`, `grpc_port` для поддержки gRPC fallback транспорта (для ISP с агрессивным DPI, например Yota/МегаФон).

**servers.json:**
- `fr1`: добавлены `grpc_inbound_id=2`, `grpc_service_name="swagagrpc"`, `grpc_domain="swaga.fortis-pro.ru"`, `grpc_port=443`.
- `us1`, `uk1`, `us2`: VPN-порт изменён на 443.

**sub_app.py:**
- В `/sub/{sub_id}` добавляется gRPC VLESS-ссылка для серверов с настроенным gRPC inbound (через `swaga.fortis-pro.ru:443` с валидным SSL, без `allowInsecure`).

**bot.py:**
- `cmd_keygen`: добавлен вывод `/connect/` URL первым (открывает страницу подключения), затем VLESS-ссылка и `/sub/` URL.
- `cmd_keygen`: после добавления клиента в основной Reality inbound — клиент также добавляется в gRPC inbound (`grpc_inbound_id`) если он настроен на сервере.
- `_create_subscription_on_server` (2 места — trial/платная и через webhook): аналогично добавляется клиент в gRPC inbound после основного.

**nginx (fr1 — swaga.fortis-pro.ru):**
- Добавлен location `/swagagrpc/` с `grpc_pass grpc://127.0.0.1:10001` для обоих блоков.
- Добавлен `/ws-test.txt` для тестирования (временный файл).

**Проблема (причина изменений):** пользователь Yota (МегаФон) получал ~892 KB/s вместо 30 MB/s из-за DPI-троттлинга TCP на нестандартных портах. gRPC через port 443 + валидный TLS обходит ограничения.

### 25.05.2026 — Объявление о сбое приложений, рекомендация Karing

**bot.py:**
- `cmd_broadcast`: обновлён текст рассылки — сообщение о сбое VPN-приложений сегодня и рекомендация использовать Karing. Добавлены inline-кнопки со ссылками на скачивание Karing для iOS и Android.

### 03.05.2026 — Полный аудит кода: устранение 4 багов

**sub_app.py:**
- Добавлена идемпотентность webhook YooKassa: если `payment.status == "succeeded"` повторный webhook молча игнорируется с 200 OK. Ранее двойной webhook создавал вторую подписку.

**bot.py — `_sync_client_to_other_servers`:**
- Исправлено логирование: теперь `ok = srv_xui.update_client(...)` — результат сохраняется и проверяется. При неудаче логируется `ERROR` с expiry_ms. Ранее "added/updated" логировалось даже при ошибке.

**bot.py — реферальный бонус (2 места: `_create_subscription_on_server` и `handle_payment_success`):**
- Добавлена 3X-UI синхронизация для реферера: после `extend_subscription(referrer_id)` получаем актуальную подписку реферера и обновляем expiry на всех серверах через `_sync_client_to_other_servers`.
- Исправлен баг (введён в этой же сессии): передавался `""` вместо `actual_server_id` как primary_server_id → теперь передаётся правильный ID.

**Остальные находки аудита (не исправлены, задокументированы):**
- HIGH: `asyncio.get_event_loop()` vs `get_running_loop()` — работает корректно на текущем Python, deprecated warning
- HIGH: sync sqlite3 в servers.py при `load_config()` — блокирует loop на ~1ms, некритично
- HIGH: race condition при параллельных платежах — SQLite сериализует записи, практически невозможно
- CRITICAL: naive datetime `.timestamp()` — сервер в UTC, поэтому баг не проявляется, но технический долг

### 03.05.2026 — Фикс: 3X-UI expiry не синхронизировался при реферальном бонусе

**bot.py:**
- Найден и исправлен баг: при начислении реферального бонуса (`REFERRAL_BONUS_DAYS`) функция `extend_subscription` обновляла только БД, но НЕ обновляла expiryTime в 3X-UI. В результате у реферальных пользователей VPN-приложения показывали дату окончания на `REFERRAL_BONUS_DAYS` дней раньше, чем реальная дата в БД.
- Исправлено в двух местах: в `_create_subscription_on_server` (строка ~2088) и `handle_payment_success` (строка ~2965). После продления через `extend_subscription` теперь вызывается `_sync_client_to_other_servers` с обновлённым `bonus_expiry_ms` для всех серверов.

**Инцидент — пользователь 943091917 (@Egorova_ke):**
- Пользователь видел "Подписка истекла" и "до 30.04.2026" в Happ Plus
- Причина: expiryTime в 3X-UI на всех 4 серверах не соответствовал DB end_date (2026-06-06)
- Вручную исправлено: expiry обновлён до 1780736099683 (06.06.2026) на fr1/us1/uk1/us2
- Пользователю нужно обновить подписку в приложении кнопкой обновления

### 15.04.2026 — Инцидент: падение us2, NXDOMAIN sub.swaga-vpn.ru, ручная активация платежей

**Инцидент 1 — us2 (31.57.38.104) недоступен с 09:53 UTC**
- SSH не отвечает (Connection timed out), xray-панель не отвечает
- Автофейловер сработал в 09:58 UTC — 2 пользователя (5025957038, 364044145) мигрированы на fr1
- Активных подписчиков на us2 больше нет
- Причина падения неизвестна — нужно проверить в панели хостинга
- **Решение:** восстановить сервер или отключить us2 из `servers.json` до решения проблемы

**Инцидент 2 — sub.swaga-vpn.ru NXDOMAIN после подключения Cloudflare (13-14 апреля)**
- При переносе NS на Cloudflare запись `sub` не была добавлена в DNS
- Результат: вебхуки YooKassa не доставлялись, пользователи не могли обновить VPN конфиги
- Исправлено 15.04.2026 ~17:00 UTC: добавлена A-запись `sub → 194.59.31.100 (Proxied)` в CF Dashboard
- Платёж 3171a849 (user=270638145, 630₽, 1y) активирован вручную: DB обновлена + 3X-UI us1 expiry обновлён

**Известные предупреждения (не критично):**
- `Chat not found` для giveaway-ключей (9877933517 и др.) и web-пользователей (-1, -2) — reminder-система пытается отправить Telegram-уведомления несуществующим чатам. Требует фикса в bot.py (пропускать user_id < 0 и giveaway-префиксы)

---

### 15.04.2026 — Дизайн LOGIN_HTML, фикс payment cards (Rocket Loader)

**web_app.py:**
- LOGIN_HTML полностью переработан в purple/dark тему (аналог лендинга и дашборда): CSS vars, radial-gradient bg, nav с logo, card с gradient title, Telegram Login Widget сверху, or-divider, email/password поля
- `data-cfasync="false"` на script в LOGIN_HTML — Cloudflare Rocket Loader не откладывает выполнение
- Payment cards в DASHBOARD_HTML: убраны `onclick` атрибуты, добавлен `addEventListener` в `DOMContentLoaded` — исправляет проблему неактивных карточек при Rocket Loader
- Сервис `swaga-web` перезапущен

---

### 14.04.2026 — Telegram Login Widget, исправление тарифов, display_name

**web_app.py:**
- Исправлен баг с тарифами: `DOMContentLoaded` никогда не срабатывал (скрипт в конце `<body>`, событие уже прошло) — заменён на IIFE `(function(){ selectPlan(first); })()`
- Добавлен маршрут `POST /api/login/telegram` — верифицирует подпись Telegram Login Widget (HMAC-SHA256), находит или создаёт web_user, для новых TG-пользователей без подписки создаёт trial, устанавливает session cookie
- `handle_login_page` теперь передаёт `bot_username=BOT_USERNAME` в LOGIN_HTML (виджет работает без плейсхолдера `{bot_username}`)
- `handle_dashboard` показывает display_name (имя из Telegram) вместо `tg_{id}@telegram.auth` для Telegram-пользователей

**database.py:**
- Добавлена колонка `display_name TEXT DEFAULT NULL` в web_users (через миграцию ALTER TABLE)
- `create_web_user_from_telegram` теперь сохраняет display_name при создании и обновляет при повторном входе

---

### 13.04.2026 — Улучшения веб-сайта: лендинг, оплата, админка, безопасность

**web_app.py:**
- Лендинг переработан: градиентный hero, блок «Что можно сделать на сайте» (подписка / оплата / подключение), pill-бейдж, glow-эффекты
- Дашборд: секция оплаты с тарифными карточками (1м/3м/1г) вместо «в боте», первый тариф выбран по умолчанию
- `POST /api/pay` — создание платежа YooKassa с `return_url=swaga-vpn.ru/dashboard?paid=1`
- `POST /api/admin/keygen` — создание гивей-ключа через admin-панель (защита токеном)
- `GET /admin` — добавлена секция «Создать ключ» поверх таблицы пользователей, 4 тарифа, копирование ссылок
- `POST /api/login`, `POST /api/register` — rate limiting (login: 10/мин, register: 5/час по IP)
- Валидация: email max 254, пароль max 128 символов
- Добавлен `_h()` — HTML-экранирование всех пользовательских данных в шаблонах (XSS-защита)
- Cookie `secure=True` добавлен
- Middleware `security_headers_middleware`: X-Frame-Options, X-Content-Type-Options, Referrer-Policy, X-XSS-Protection
- Admin token в JS через `json.dumps()` вместо прямой строковой вставки
- Исправлен redirect после регистрации: относительный `/connect/{sub_id}` вместо `sub.swaga-vpn.ru`
- `/connect/` и `/sub/` добавлены в nginx для `swaga-vpn.ru` (ранее только для `sub.swaga-vpn.ru`)
- `provision_giveaway_key()` — новая функция создания ключа, аналог `/keygen` бота

**bot.py:**
- `handle_payment_success`: для web-пользователей (user_id < 0) пропускает Telegram-уведомление, но активирует подписку и уведомляет админов с пометкой «🌐 Web ID»
- Добавлена команда `/web_user EMAIL` — поиск web-пользователя по email, показывает статус подписки

**yookassa_payment.py:**
- `create_payment()` принимает опциональный `return_url` (для web-платежей — возврат в дашборд, не в Telegram)

**database.py:**
- `get_all_web_users_with_subs()` — JOIN web_users + subscriptions для admin-панели
- `create_user` экспортирован для использования в web_app.py

**config.py:**
- Добавлена константа `WEB_ADMIN_TOKEN` (из .env)

**.env:**
- Добавлен `WEB_ADMIN_TOKEN` (64-символьный hex)

---

### 13.04.2026 — Веб-сайт SWAGA VPN (лендинг + регистрация без Telegram)

**web_app.py** (НОВЫЙ ФАЙЛ):
- Aiohttp веб-сервер на порту 8890 (`127.0.0.1:8890`)
- `GET /` — публичный лендинг с описанием, тарифами и инструкцией
- `GET /register`, `POST /api/register` — регистрация через email+пароль, auto-создание trial-подписки на всех серверах
- `GET /login`, `POST /api/login` — вход, HMAC-подписанные session cookies
- `GET /dashboard` — личный кабинет: статус подписки, кнопка /connect
- `GET /logout` — выход
- PBKDF2-SHA256 хеширование паролей (встроенный Python, без зависимостей)
- Синтетический user_id = -(web_user_id) для совместимости с таблицей users

**database.py:**
- Добавлена функция `init_web_users_table()` — создаёт таблицу `web_users`
- Добавлена функция `create_web_user(email, password_hash)` — создаёт web_user + запись в users
- Добавлены `get_web_user_by_email()`, `get_web_user_by_id()`, `set_web_user_sub_id()`

**config.py:**
- Добавлены константы `WEB_SECRET_KEY` и `WEB_LISTEN_PORT` (из .env)

**.env:**
- Добавлены `WEB_SECRET_KEY` (рандомный 64-hex) и `WEB_LISTEN_PORT=8890`

**/etc/nginx/sites-available/swaga-vpn.conf:**
- Для `swaga-vpn.ru` заменён `return 404` на `proxy_pass http://127.0.0.1:8890/`

**/etc/systemd/system/swaga-web.service** (НОВЫЙ ФАЙЛ):
- Systemd сервис `swaga-web`, enabled и запущен

---

### 11.04.2026 — Обновление /connect страницы и инструкций

**sub_app.py:**
- Исправлен баг: Happ Plus получал только первый сервер (Францию) вместо всех. Теперь `happAllConfigs` содержит все VLESS-ссылки через `\n` (JSON-encoded)
- Переименовано «Happ» → «Happ Plus» везде
- Добавлена вкладка **Karing** с deeplink `karing://install-config?url=...&name=SWAGA+VPN`
- Исправлен deeplink Hiddify: `hiddify://install-sub/?url=` → `hiddify://import/{url}#SWAGA+VPN` (старый формат удалён из актуальной версии приложения)
- Исправлена ссылка Happ Plus в App Store: `id6504287480` → `id6746188973`
- Добавлено предупреждение об открытии в Telegram WebView (JS-детектор `TelegramWebviewProxy`)
- Добавлен раздел «Какое приложение выбрать?» с карточками iOS / Android / Desktop и прямыми ссылками на скачивание
- Добавлена карточка **статуса подписки** (дней осталось + дата истечения, цвет по статусу)
- Добавлена брендинг-карточка «Управление подпиской и оплата → 🚀 @Swaga_vpnbot»
- Добавлена подпись «Выберите приложение» перед вкладками
- `limitIp` в xui_api.py: 3 устройства (не 2)

**bot.py:**
- Обновлён `INSTRUCTION_TEXT`: разделён на iOS / Android, добавлены актуальные приложения с пометками о доступности в App Store РФ

**keyboards.py:**
- Кнопка iOS → Happ Plus (`id6746188973`)
- Кнопка Android → Hiddify (Google Play)
- Добавлена кнопка Karing (iOS + Android APK)

**Актуальные приложения на 11.04.2026:**

| Приложение | iOS App Store РФ | Android Google Play |
|---|---|---|
| Happ Plus | ✅ `id6746188973` | ✅ |
| Karing | ✅ `id6472431552` | ❌ только APK (karing.app) |
| V2RayTun | ❌ удалён (март 2026) | ❌ удалён (май 2025) |
| Hiddify | ✅ | ✅ |
