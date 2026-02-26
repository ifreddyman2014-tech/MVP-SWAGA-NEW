# Инструкция по накату изменений

## Быстрый деплой

```bash
# 1. Перейти в директорию проекта
cd /root/MVP-SWAGA-NEW

# 2. Подтянуть изменения из ветки
git fetch origin claude/check-status-bH5rv
git merge origin/claude/check-status-bH5rv

# 3. Перезапустить сервисы (если нужно)
systemctl restart swaga-bot swaga-support

# 4. Проверить логи
journalctl -u swaga-bot -f
```

## Альтернатива: использовать deploy.sh

```bash
cd /root/MVP-SWAGA-NEW
./deploy.sh
```

Скрипт deploy.sh автоматически:
- Подтянет последние изменения
- Установит зависимости
- Перезапустит сервисы
- Синхронизирует клиентов

## Что было исправлено?

**Коммит:** `bdea30b` - fix: change HTTP to HTTPS in subscription management scripts

**Изменённые файлы:**
- `bulk_extend_subscriptions.py` - массовое продление подписок
- `extend_subscription.py` - продление одной подписки
- `sync_all_subscriptions.py` - синхронизация всех подписок

**Суть изменений:**
Исправлена ошибка подключения к x-ui панелям - теперь используется HTTPS вместо HTTP.

## После наката проверьте работу

```bash
# Проверить статус подписок
python3 check_subscriptions_status.py

# Синхронизировать подписки с серверов
python3 sync_all_subscriptions.py

# Проверить, что бот работает
systemctl status swaga-bot

# Посмотреть последние логи
tail -100 /root/MVP-SWAGA-NEW/bot.log
```

## Команды для управления

```bash
# Статус сервисов
systemctl status swaga-bot swaga-support

# Перезапуск
systemctl restart swaga-bot

# Остановка
systemctl stop swaga-bot

# Логи в реальном времени
journalctl -u swaga-bot -f
```
