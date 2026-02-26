# 🚀 Деплой на продакшн

## 📋 Checklist перед деплоем

### 1. Проверка зависимостей

Убедитесь что установлены:
- ✅ Python 3.11+
- ✅ aiosqlite
- ✅ aiohttp
- ✅ requests

```bash
pip3 install -r requirements.txt
```

### 2. Проверка файлов

Новые файлы для деплоя:
- ✅ `check_subscriptions_status.py`
- ✅ `bulk_extend_subscriptions.py`
- ✅ `sync_all_subscriptions.py`
- ✅ `extend_subscription.py`
- ✅ `sync_subscription_to_db.py`
- ✅ `SUBSCRIPTION_MANAGEMENT.md`
- ✅ `QUICKSTART.md`

---

## 🔄 Процесс деплоя

### Вариант 1: Быстрый деплой через git pull

```bash
# На продакшн сервере
cd /path/to/MVP-SWAGA-NEW
git pull origin claude/check-status-bH5rv
python3 check_subscriptions_status.py  # Проверка
```

### Вариант 2: Через merge в main

```bash
# Локально
git checkout main
git merge claude/check-status-bH5rv
git push origin main

# На продакшн сервере
cd /path/to/MVP-SWAGA-NEW
git pull origin main
```

---

## ✅ После деплоя

### 1. Проверка работы

```bash
python3 check_subscriptions_status.py
```

### 2. Импорт подписок (если нужно)

```bash
python3 sync_all_subscriptions.py --dry-run
python3 sync_all_subscriptions.py
```

### 3. Настройка cron (опционально)

```bash
crontab -e
# Добавить:
0 3 * * 0 cd /path/to/MVP-SWAGA-NEW && python3 bulk_extend_subscriptions.py --days-before 14 --extend-days 30
```

