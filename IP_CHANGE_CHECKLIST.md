# 🔄 Чеклист смены IP для главного сервера

## ⚠️ ДО СМЕНЫ IP

### 1. Проверить что на сервере
```bash
# На сервере Франции (194.59.30.107):
ps aux | grep -E "bot.py|main.py|docker"
docker ps
systemctl status nginx postgres
```

**Записать что работает:**
- [ ] Telegram бот (bot.py / main.py)
- [ ] PostgreSQL база данных
- [ ] Nginx веб-сервер
- [ ] Docker контейнеры
- [ ] 3X-UI VPN панель
- [ ] Subscription сервер

---

### 2. Создать бэкапы

```bash
# База данных
docker compose exec postgres pg_dump -U swaga_user swaga > backup_$(date +%Y%m%d).sql

# Конфигурация
tar -czf config_backup_$(date +%Y%m%d).tar.gz \
    /home/user/MVP-SWAGA-NEW/.env \
    /etc/nginx/sites-available/ \
    /etc/letsencrypt/

# Данные пользователей (если есть файлы)
cp -r /home/user/MVP-SWAGA-NEW/vpn_bot.db backup/
```

---

### 3. Записать текущие DNS настройки

```bash
# Проверить куда указывают домены СЕЙЧАС
nslookup swaga-vpn.ru
nslookup sub.swaga-vpn.ru

# Записать текущие A-записи:
# swaga-vpn.ru     → _______________
# sub.swaga-vpn.ru → _______________
```

---

### 4. Подготовить список активных подписок

```bash
# На сервере с БД:
docker compose exec postgres psql -U swaga_user -d swaga -c "
SELECT
    u.telegram_id,
    u.username,
    s.plan,
    s.end_date,
    COUNT(k.id) as keys_count
FROM subscriptions s
JOIN users u ON s.user_id = u.id
LEFT JOIN keys k ON s.id = k.subscription_id
WHERE s.is_active = true
GROUP BY u.telegram_id, u.username, s.plan, s.end_date
ORDER BY s.end_date DESC;
" > active_subscriptions.txt
```

---

## ⏸️ ПЕРЕД СМЕНОЙ IP

### 1. Уведомить пользователей (опционально)

```python
# В боте отправить сообщение всем активным пользователям
# Примерный текст:
"""
⚠️ Технические работы

Сегодня в 22:00 МСК будут проводиться технические работы.
Возможны кратковременные перерывы в работе (10-15 минут).

После работ вам потребуется:
1. Удалить старую конфигурацию из приложения
2. Получить новую через /start

Приносим извинения за неудобства.
"""
```

---

### 2. Остановить бота (чтобы не было конфликтов)

```bash
docker compose stop bot
# или
pkill -f "python.*main.py"

# Оставить работать ТОЛЬКО VPN (если нужно минимизировать даунтайм)
```

---

## 🔄 ВО ВРЕМЯ СМЕНЫ IP

### 1. У хостера:
- [ ] Пересоздать VPS с новым IP
- [ ] Или заказать новый IP (если есть опция)
- [ ] Записать **НОВЫЙ IP**: `______________`

---

### 2. Развернуть систему на новом IP:

```bash
# Если пересоздали сервер:

# 1. Установить зависимости
apt update
apt install -y docker.io docker-compose nginx certbot python3-certbot-nginx git

# 2. Восстановить код
cd /home/user
git clone <repo-url> MVP-SWAGA-NEW
cd MVP-SWAGA-NEW

# 3. Восстановить .env
# (загрузить backup_config.tar.gz)

# 4. Восстановить базу данных
docker compose up -d postgres
sleep 10
cat backup_YYYYMMDD.sql | docker compose exec -T postgres psql -U swaga_user -d swaga

# 5. Обновить servers.json с новым IP
nano servers.json
# Заменить старый IP на новый

# 6. Синхронизировать серверы
docker compose exec bot python sync_servers.py
```

---

## 🌐 ОБНОВИТЬ DNS (КРИТИЧНО!)

### 1. Зайти в панель регистратора домена

**Обновить A-записи:**

```
swaga-vpn.ru        A    <НОВЫЙ_IP>    TTL 300
sub.swaga-vpn.ru    A    <НОВЫЙ_IP>    TTL 300
```

**Если используется Cloudflare:**
- Временно отключить прокси (оранжевое облако → серое)
- Обновить IP
- Подождать 5-10 минут
- Включить прокси обратно

---

### 2. Дождаться обновления DNS (5-15 минут)

```bash
# Проверять пока не обновится:
watch -n 10 'nslookup swaga-vpn.ru | grep Address'

# Должно показать НОВЫЙ IP
```

---

## 🔐 ОБНОВИТЬ SSL СЕРТИФИКАТЫ

```bash
# После обновления DNS:

# 1. Остановить nginx (если запущен)
systemctl stop nginx

# 2. Получить новые сертификаты
certbot certonly --standalone \
    -d swaga-vpn.ru \
    -d sub.swaga-vpn.ru \
    --non-interactive \
    --agree-tos \
    -m your-email@example.com

# 3. Настроить nginx
cp /path/to/backup/nginx/config /etc/nginx/sites-available/swaga-vpn.ru
ln -sf /etc/nginx/sites-available/swaga-vpn.ru /etc/nginx/sites-enabled/

# 4. Проверить конфиг
nginx -t

# 5. Запустить nginx
systemctl start nginx
```

---

## 🤖 ЗАПУСТИТЬ БОТА

```bash
cd /home/user/MVP-SWAGA-NEW

# 1. Проверить что БД работает
docker compose exec postgres psql -U swaga_user -d swaga -c "SELECT COUNT(*) FROM users;"

# 2. Запустить бота
docker compose up -d bot

# 3. Проверить логи
docker compose logs -f bot

# Должно быть:
# ✅ Database initialized
# ✅ Bot started
# ✅ Webhook server running on 0.0.0.0:8000
```

---

## 🧪 ТЕСТИРОВАНИЕ

### 1. Проверить webhook

```bash
curl https://swaga-vpn.ru/webhook/yookassa
# Должен вернуть: 405 Method Not Allowed (это нормально для GET)

# Или:
curl -X POST https://swaga-vpn.ru/webhook/yookassa \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
# Должен вернуть статус без ошибки
```

---

### 2. Проверить subscription server

```bash
curl https://sub.swaga-vpn.ru/health
# Должен вернуть: {"status": "ok"}

curl https://sub.swaga-vpn.ru/sub/test123
# Должен вернуть ошибку "Subscription not found" (это нормально)
```

---

### 3. Проверить бота в Telegram

- [ ] /start — бот отвечает
- [ ] Создать тестовую подписку (админу)
- [ ] Проверить что генерируется новый ключ
- [ ] Проверить что ключ содержит **НОВЫЙ IP**
- [ ] Подключиться через V2Ray/Hiddify — работает

---

## 🔄 ОБНОВИТЬ YOOKASSA WEBHOOK (если нужно)

```bash
# Зайти в личный кабинет YooKassa:
# https://yookassa.ru/my/merchant/<shop_id>/integration/http-notifications

# Проверить URL:
# https://swaga-vpn.ru/webhook/yookassa

# Нажать "Проверить уведомление"
# Должно вернуть: ✅ Успешно
```

---

## 🔑 РЕГЕНЕРИРОВАТЬ КЛЮЧИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ

### Вариант А: Автоматически (если написан скрипт)

```bash
docker compose exec bot python regenerate_keys.py --server-id fr1
```

---

### Вариант Б: Через бота (вручную для каждого)

Отправить пользователям сообщение:

```
⚠️ Обновление сервера завершено!

Для продолжения работы:
1. Удалите старую конфигурацию из приложения
2. Нажмите /start и получите новую

Ваша подписка осталась активной.
```

---

### Вариант В: Через SQL (массово)

```sql
-- Пометить все ключи на сервере fr1 как неактивные
UPDATE keys
SET is_active = false
WHERE server_id IN (
    SELECT id FROM servers WHERE name = 'Франция'
);

-- Бот автоматически создаст новые при следующем /start пользователя
```

---

## ✅ ФИНАЛЬНАЯ ПРОВЕРКА

- [ ] DNS указывает на новый IP
- [ ] SSL сертификаты работают
- [ ] Nginx работает и отвечает
- [ ] PostgreSQL база данных доступна
- [ ] Бот запущен и отвечает в Telegram
- [ ] Webhook от YooKassa работает
- [ ] Subscription сервер работает
- [ ] Тестовая подписка создается с новым IP
- [ ] VPN подключение работает
- [ ] Все активные пользователи уведомлены

---

## 📊 МОНИТОРИНГ (первые 24 часа)

```bash
# Следить за логами бота
docker compose logs -f bot | grep -i error

# Следить за подключениями к VPN
docker compose exec xray xray api stats -server=127.0.0.1:10085

# Следить за платежами (если есть)
docker compose exec postgres psql -U swaga_user -d swaga -c "
SELECT * FROM payments
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
"
```

---

## 🚨 ПЛАН Б: Откат на старый IP

Если что-то пошло не так:

```bash
# 1. Обновить DNS обратно на старый IP
swaga-vpn.ru        A    194.59.30.107

# 2. Подождать обновления DNS (5-10 минут)

# 3. Запустить бота на старом сервере (если еще работает)
```

---

## 📈 ПОСЛЕ СМЕНЫ IP

- [ ] Обновить документацию (записать новый IP)
- [ ] Обновить мониторинг (новый IP в uptime сервисе)
- [ ] Обновить бэкап-скрипты (если используют IP)
- [ ] Убедиться что старый сервер выключен (чтобы не было двойных биллингов)

---

## 💡 РЕКОМЕНДАЦИИ НА БУДУЩЕЕ

**Чтобы избежать проблем при следующей смене IP:**

1. ✅ Всегда использовать **домены** вместо IP (уже есть)
2. ✅ В коде и конфигах использовать **имена контейнеров** (`postgres:5432`) а не IP
3. ✅ Настроить **автоматическое обновление SSL** (certbot renew в cron)
4. ✅ Хранить **бэкапы** БД (ежедневные)
5. ✅ Написать **скрипт массовой регенерации ключей**

---

**Время на полную миграцию:** 30-60 минут
**Даунтайм для пользователей:** 10-20 минут (пока DNS обновится)
