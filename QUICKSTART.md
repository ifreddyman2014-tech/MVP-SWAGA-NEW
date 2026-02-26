# ⚡ Быстрый старт - Управление подписками

## 🚀 Самые частые команды

### 1️⃣ Проверить состояние всех подписок
```bash
python3 check_subscriptions_status.py
```

### 2️⃣ Продлить все истекшие подписки на 90 дней
```bash
python3 bulk_extend_subscriptions.py --include-expired --extend-days 90
```

### 3️⃣ Продлить подписки, истекающие в ближайшие 7 дней
```bash
python3 bulk_extend_subscriptions.py --days-before 7 --extend-days 30
```

### 4️⃣ Посмотреть что будет сделано (безопасно)
```bash
python3 bulk_extend_subscriptions.py --include-expired --dry-run
```

### 5️⃣ Импорт подписок с x-ui панели
```bash
python3 sync_all_subscriptions.py
```

---

## 📊 Фильтрация

### Только UK сервер
```bash
python3 check_subscriptions_status.py --server uk1
python3 bulk_extend_subscriptions.py --server uk1 --extend-days 365
```

### Только истекшие
```bash
python3 check_subscriptions_status.py --show-expired
```

### Экспорт в CSV
```bash
python3 check_subscriptions_status.py --export-csv report.csv
```

---

## ⏰ Автоматизация (cron)

Продлевать каждую неделю в воскресенье в 3:00:
```bash
crontab -e
# Добавить:
0 3 * * 0 cd /home/user/MVP-SWAGA-NEW && python3 bulk_extend_subscriptions.py --days-before 14 --extend-days 30 >> /var/log/vpn-extend.log 2>&1
```

---

## 📚 Полная документация

```bash
cat SUBSCRIPTION_MANAGEMENT.md
```

---

## 🆘 Помощь

```bash
python3 check_subscriptions_status.py --help
python3 bulk_extend_subscriptions.py --help
python3 sync_all_subscriptions.py --help
```
