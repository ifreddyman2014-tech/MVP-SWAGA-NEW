# 🔧 Управление подписками SWAGA VPN

Полный набор скриптов для автоматизации управления подписками VPN.

---

## 📋 Доступные скрипты

### 1. `check_subscriptions_status.py` - Проверка состояния ⭐

**НАЧНИТЕ С ЭТОГО!** Показывает текущее состояние всех подписок.

**Использование:**

```bash
# Проверить все подписки
python3 check_subscriptions_status.py

# Проверить только UK сервер
python3 check_subscriptions_status.py --server uk1

# Показать только истекшие
python3 check_subscriptions_status.py --show-expired

# Экспорт в CSV
python3 check_subscriptions_status.py --export-csv subscriptions.csv
```

**Что показывает:**
- ✅ Активные подписки
- ⚠️ Истекающие скоро (< 30 дней)
- ❌ Истекшие подписки
- 📊 Статистика по серверам
- 💡 Рекомендации по продлению

---

### 2. `bulk_extend_subscriptions.py` - Массовое продление ⭐

**САМЫЙ ПОЛЕЗНЫЙ!** Автоматически продлевает множество подписок одной командой.

**Использование:**

```bash
# Продлить все истекшие подписки на 90 дней
python3 bulk_extend_subscriptions.py --include-expired --extend-days 90

# Продлить подписки, истекающие в ближайшие 7 дней
python3 bulk_extend_subscriptions.py --days-before 7 --extend-days 30

# Продлить только UK сервер на год
python3 bulk_extend_subscriptions.py --server uk1 --extend-days 365

# Посмотреть что будет сделано (dry-run)
python3 bulk_extend_subscriptions.py --include-expired --dry-run

# Продлить в БД и на x-ui панели
python3 bulk_extend_subscriptions.py --include-expired --update-panel --extend-days 90
```

**Параметры:**
- `--days-before N` - Продлить истекающие в ближайшие N дней
- `--extend-days N` - На сколько дней продлить
- `--include-expired` - Включить истекшие подписки
- `--server SERVER` - Только указанный сервер (uk1, us1, fr1, etc.)
- `--plan PLAN` - Только указанный план (trial, 1m, 3m, 6m, 12m)
- `--update-panel` - Обновить даты на x-ui панели (требует доступа)
- `--dry-run` - Показать что будет сделано, не выполняя

---

### 3. `sync_all_subscriptions.py` - Синхронизация с x-ui

Загружает все подписки со всех x-ui панелей и синхронизирует с базой данных.

**Использование:**

```bash
# Синхронизировать все серверы
python3 sync_all_subscriptions.py

# Синхронизировать только UK
python3 sync_all_subscriptions.py --server uk1

# Посмотреть что будет синхронизировано
python3 sync_all_subscriptions.py --dry-run

# Обновить существующие подписки
python3 sync_all_subscriptions.py --update-existing
```

**Когда использовать:**
- Вы создали подписки вручную через x-ui панель
- Нужно загрузить все подписки в базу данных
- После миграции или восстановления БД

---

### 4. `extend_subscription.py` - Одиночное продление

Автоматически продлевает подписку на x-ui панели и синхронизирует с базой данных.

**Использование:**

```bash
# Продлить до указанной даты
python3 extend_subscription.py <UUID> --date YYYY-MM-DD

# Продлить и добавить в базу данных
python3 extend_subscription.py <UUID> --date YYYY-MM-DD --add-to-db

# Продлить на другом сервере
python3 extend_subscription.py <UUID> --date YYYY-MM-DD --server de1
```

**Примеры:**

```bash
# Продлить UUID до 5 июля 2026
python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc --date 2026-07-05

# Продлить до 5 июля 2026 и добавить в БД
python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc --date 2026-07-05 --add-to-db

# Продлить на год вперёд (по умолчанию)
python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc
```

**Требования:**
- Доступ к x-ui панели (может не работать в изолированных окружениях)
- Запускать на сервере с доступом к панели управления

---

### 5. `sync_subscription_to_db.py` - Ручная синхронизация одной подписки

Добавляет или обновляет одну подписку в базе данных бота (без изменения x-ui панели).

**Использование:**

```bash
python3 sync_subscription_to_db.py <USER_ID> <UUID> <END_DATE> [OPTIONS]

# Опции:
#   --sub-id SUB_ID      XUI subscription ID (опционально)
#   --server SERVER      ID сервера (по умолчанию: uk1)
#   --plan PLAN          Тип плана: manual, trial, 1m, 3m, 6m, 12m
```

**Примеры:**

```bash
# Добавить подписку с auto-генерацией sub_id
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05

# Добавить с указанием sub_id
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 \
  --sub-id l1ml1zsf3rm7hrt7 --server uk1

# Добавить подписку на 12 месяцев
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 \
  --plan 12m
```

**Когда использовать:**
- Вы вручную продлили подписку через веб-интерфейс x-ui
- Нужно добавить существующую подписку в базу данных
- Подписка создана вручную и не синхронизирована

---

## 🚀 Типичные сценарии использования

### Сценарий 1: Проверка и продление всех истекших подписок

```bash
# Шаг 1: Проверить состояние
python3 check_subscriptions_status.py

# Шаг 2: Продлить все истекшие на 90 дней
python3 bulk_extend_subscriptions.py --include-expired --extend-days 90

# Шаг 3: Проверить результат
python3 check_subscriptions_status.py
```

**Результат:** Все истекшие подписки продлены в базе данных.

---

### Сценарий 2: Автоматическое продление подписок, истекающих скоро

```bash
# Продлить подписки, истекающие в ближайшие 14 дней, на 30 дней
python3 bulk_extend_subscriptions.py --days-before 14 --extend-days 30
```

**Когда использовать:** Запускайте еженедельно через cron для автоматического продления.

---

### Сценарий 3: Импорт всех подписок с x-ui панели

```bash
# Шаг 1: Посмотреть что будет импортировано
python3 sync_all_subscriptions.py --dry-run

# Шаг 2: Импортировать
python3 sync_all_subscriptions.py

# Шаг 3: Проверить результат
python3 check_subscriptions_status.py
```

**Когда использовать:** После создания подписок вручную через x-ui панель.

---

### Сценарий 4: Продление с обновлением x-ui панели

```bash
# Продлить в БД и на панели одновременно
python3 bulk_extend_subscriptions.py \
  --include-expired \
  --extend-days 365 \
  --update-panel
```

**⚠️ Требуется:** Прямой доступ к x-ui панелям.

---

### Сценарий 5: Экспорт отчёта о подписках

```bash
# Экспортировать все подписки в CSV
python3 check_subscriptions_status.py --export-csv report.csv --show-all

# Только истекшие в CSV
python3 check_subscriptions_status.py --show-expired --export-csv expired.csv
```

**Результат:** Файл CSV для анализа в Excel/Google Sheets.

---

### Сценарий 6: Настройка автоматического продления через cron

Добавьте в crontab:

```bash
# Открыть crontab
crontab -e

# Добавить задачу: продлевать каждую неделю (воскресенье в 3:00)
0 3 * * 0 cd /path/to/MVP-SWAGA-NEW && python3 bulk_extend_subscriptions.py --days-before 14 --extend-days 30 >> /var/log/vpn-extend.log 2>&1
```

---

## 🔄 Пошаговая инструкция: Продление истекшей подписки

### Вариант 1: Автоматическое продление (РЕКОМЕНДУЕТСЯ)

**Шаг 1:** Запустите скрипт на сервере с доступом к x-ui панели:

```bash
python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc \
  --date 2026-07-05 \
  --add-to-db
```

**Готово!** Подписка продлена и синхронизирована! 🎉

---

### Вариант 2: Ручное продление через веб-интерфейс

**Шаг 1:** Откройте x-ui панель в браузере:

```
🔗 URL: http://45.95.18.254:4378/Hi42hxe2dAuW5scOcz
👤 Login: SXqnreu3JL
🔑 Password: uvHWpWB2Ft
```

**Шаг 2:** Перейдите в раздел управления клиентами:

```
Inbounds → Port 17720 → Clients
```

**Шаг 3:** Найдите клиента:

```
Email: tg_364044145_1771431227
UUID: 6c23242d-2d76-4479-9c58-0d53f8153afc
```

**Шаг 4:** Нажмите кнопку **EDIT** (карандаш)

**Шаг 5:** Измените **Expiry Time**:

```
Новая дата: 2026-07-05 23:59:59
```

**Шаг 6:** Нажмите **SAVE**

**Шаг 7:** Синхронизируйте с базой данных:

```bash
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 \
  --sub-id l1ml1zsf3rm7hrt7 \
  --server uk1
```

**Готово!** 🎉

---

## 📊 Проверка подписки

### Проверка в базе данных:

```bash
python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('vpn_bot.db')
cursor = conn.cursor()
cursor.execute("SELECT * FROM subscriptions WHERE vless_uuid = ?",
               ("6c23242d-2d76-4479-9c58-0d53f8153afc",))
print(cursor.fetchone())
conn.close()
EOF
```

### Проверка subscription URL:

```
https://sub.swaga-vpn.ru/sub/l1ml1zsf3rm7hrt7
```

Откройте в браузере - должен вернуть base64-закодированную VLESS ссылку.

### Проверка в приложении:

```
https://sub.swaga-vpn.ru/connect/l1ml1zsf3rm7hrt7
```

Откройте на телефоне - должно автоматически импортировать в V2RayTun.

---

## 🗂️ Доступные серверы

| ID | Название | IP | Порт | Статус |
|----|----------|----|----- |--------|
| `uk1` | Великобритания 🇬🇧 | 45.95.18.254 | 17720 | ✅ Enabled |
| `us1` | США 🇺🇸 | 80.76.49.140 | 443 | ✅ Enabled |
| `fr1` | Франция 🇫🇷 | 194.59.30.107 | 54232 | ✅ Enabled |
| `fi1` | Финляндия 🇫🇮 | 144.31.132.116 | 18971 | ❌ Disabled |
| `de1` | Германия 🇩🇪 | 150.241.77.138 | 19571 | ❌ Disabled |
| `lv1` | Латвия 🇱🇻 | 155.212.225.26 | 443 | ❌ Disabled |

---

## 🔐 Доступ к x-ui панелям

### Великобритания (uk1)
```
URL: http://45.95.18.254:4378/Hi42hxe2dAuW5scOcz
Username: SXqnreu3JL
Password: uvHWpWB2Ft
```

### США (us1)
```
URL: http://80.76.49.140:2053/8J0lp7fw3i0SRtKAp6
Username: 6v94Sn6w9D
Password: sCIHDcxQF1
```

### Франция (fr1)
```
URL: http://194.59.30.107:4444/iV31Zfverpgxjo2m6D
Username: cDEPkmdjId
Password: ORnzDpmBR1
```

---

## ❓ FAQ

### Q: Почему в приложении показывается дата "до 5 июля", а на панели подписка истекла?

**A:** Дата в приложении берётся из поля `remarks` (названия конфига), а не с сервера. Это просто текст. Реальная дата проверяется на x-ui панели.

### Q: UUID существует на панели, но нет в базе данных бота?

**A:** Подписка была создана вручную через x-ui, а не через бота. Используйте `sync_subscription_to_db.py` для синхронизации.

### Q: Не могу подключиться к x-ui панели из скрипта?

**A:** Скрипты требуют прямого доступа к серверу. Запускайте их на сервере или используйте ручное продление через веб-интерфейс.

### Q: Как узнать user_id для синхронизации?

**A:** User ID содержится в email клиента в формате `tg_<USER_ID>_<TIMESTAMP>`. Например, `tg_364044145_1771431227` → user_id = `364044145`.

### Q: Подписка продлена, но не работает?

**A:** Проверьте:
1. Дата на x-ui панели обновлена
2. Клиент **Enabled** (галочка включена)
3. Приложение обновило конфигурацию (переподключитесь)

---

## 📝 Решённая проблема

**Исходная проблема:**
```
UUID: 6c23242d-2d76-4479-9c58-0d53f8153afc
Статус на панели: ИСЧЕРПАНО (истёк 25.02.2026)
Статус в БД: НЕ НАЙДЕНО
Статус в приложении: "Активна до 5 июля" (текст из remarks)
```

**Решение:**
```bash
# Добавлена в базу данных
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 \
  --sub-id l1ml1zsf3rm7hrt7 --server uk1

# Результат:
✅ Подписка в БД: до 2026-07-05
✅ Subscription URL работает
⚠️  Нужно продлить на x-ui панели вручную или через extend_subscription.py
```

**Следующий шаг:** Продлить UUID на x-ui панели до 2026-07-05.

---

## 🚀 Быстрые команды

### Проверка и мониторинг

```bash
# Проверить все подписки
python3 check_subscriptions_status.py

# Только истекшие
python3 check_subscriptions_status.py --show-expired

# Экспорт в CSV
python3 check_subscriptions_status.py --export-csv report.csv
```

### Массовое продление

```bash
# Продлить все истекшие на 90 дней
python3 bulk_extend_subscriptions.py --include-expired --extend-days 90

# Продлить истекающие в ближайшие 7 дней на 30 дней
python3 bulk_extend_subscriptions.py --days-before 7 --extend-days 30

# Dry-run (посмотреть что будет сделано)
python3 bulk_extend_subscriptions.py --include-expired --dry-run
```

### Синхронизация с x-ui

```bash
# Импортировать все подписки со всех серверов
python3 sync_all_subscriptions.py

# Только UK сервер
python3 sync_all_subscriptions.py --server uk1

# Обновить существующие подписки
python3 sync_all_subscriptions.py --update-existing
```

### Одиночные операции

```bash
# Продлить одну подписку до 5 июля 2026
python3 extend_subscription.py 6c23242d-2d76-4479-9c58-0d53f8153afc --date 2026-07-05 --add-to-db

# Добавить одну подписку в БД вручную
python3 sync_subscription_to_db.py 364044145 6c23242d-2d76-4479-9c58-0d53f8153afc 2026-07-05 \
  --sub-id l1ml1zsf3rm7hrt7 --server uk1
```

### SQL запросы

```bash
# Проверить подписку в БД
sqlite3 vpn_bot.db "SELECT * FROM subscriptions WHERE vless_uuid = '6c23242d-2d76-4479-9c58-0d53f8153afc'"

# Все активные подписки
sqlite3 vpn_bot.db "SELECT xui_sub_id, vless_uuid, end_date, server_id FROM subscriptions WHERE is_active = 1"

# Подписки истекающие в ближайшие 7 дней
sqlite3 vpn_bot.db "SELECT xui_sub_id, end_date FROM subscriptions WHERE date(end_date) <= date('now', '+7 days')"
```

---

✅ **Подписка синхронизирована с базой данных!**

⚠️ **Следующий шаг:** Зайдите на x-ui панель и продлите срок действия UUID до **2026-07-05 23:59:59**
