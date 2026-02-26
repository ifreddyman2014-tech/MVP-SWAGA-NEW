# 🚀 Деплой новых серверов на продакшн

## ✅ Что готово:
- ✅ Серверы us1 и us2 добавлены в `servers.json`
- ✅ Скрипт миграции для существующих пользователей готов
- ✅ Документация создана
- ✅ Все изменения закоммичены в ветку `claude/check-status-bH5rv`

---

## 📋 План деплоя на продакшн:

### Вариант 1: Деплой на текущем сервере (РЕКОМЕНДУЕТСЯ)

```bash
# 1. Подключитесь к продакшн-серверу
ssh root@<your-production-server>

# 2. Перейдите в директорию бота
cd /root/MVP-SWAGA-NEW  # или путь к вашему боту

# 3. Стяните изменения из ветки
git fetch origin
git checkout claude/check-status-bH5rv
git pull origin claude/check-status-bH5rv

# 4. Перезапустите бота
systemctl restart swaga-vpn-bot
# или
docker-compose restart

# 5. Проверьте что бот запустился
systemctl status swaga-vpn-bot
# или
docker-compose ps

# 6. Проверьте логи
tail -f /var/log/swaga-vpn-bot.log
# или
docker-compose logs -f
```

### Вариант 2: Через GitHub Pull Request

```bash
# 1. Создайте PR из ветки claude/check-status-bH5rv в main/master
# 2. Смержите PR на GitHub
# 3. На продакшн-сервере:

git checkout main  # или master
git pull origin main
systemctl restart swaga-vpn-bot
```

---

## 🔄 Миграция существующих пользователей (ОПЦИОНАЛЬНО)

Если хотите добавить **существующих пользователей** на новые серверы:

```bash
# На продакшн-сервере после деплоя
cd /root/MVP-SWAGA-NEW

# Тестовый запуск (посмотреть что будет сделано)
python3 add_servers_to_existing_users.py --dry-run

# Реальная миграция (добавит пользователей на us1 и us2)
python3 add_servers_to_existing_users.py
```

**Внимание:** Миграция нужна только если хотите чтобы текущие пользователи получили доступ к новым серверам. Новые пользователи автоматически смогут выбирать новые серверы при покупке.

---

## ✅ Проверка после деплоя:

1. **Проверьте что бот отвечает:**
   - Отправьте `/start` боту
   - Проверьте отображение серверов

2. **Проверьте новые серверы:**
   - Попробуйте купить подписку (или тестовую)
   - Убедитесь что us1 и us2 доступны в списке

3. **Проверьте логи на ошибки:**
   ```bash
   tail -100 /var/log/swaga-vpn-bot.log | grep -i error
   ```

---

## 🆘 Откат изменений (если что-то пошло не так):

```bash
# Вернитесь на предыдущий коммит
git log --oneline -5  # найдите хеш нужного коммита
git checkout <previous-commit-hash>
systemctl restart swaga-vpn-bot

# Или вернитесь на основную ветку
git checkout main
git pull origin main
systemctl restart swaga-vpn-bot
```

---

## 📊 Новые серверы:

| ID | Название | Host | Location | Status |
|----|----------|------|----------|--------|
| us1 | США 1 | 185.217.125.182 | 🇺🇸 US | ✅ Активен |
| us2 | США 2 | 185.217.125.183 | 🇺🇸 US | ✅ Активен |

**API URL:** https://us1.swaga.tech:8443 / https://us2.swaga.tech:8443
**Transport:** TCP Reality
**SNI:** www.speedtest.net

---

## 🎉 После успешного деплоя:

1. ✅ Бот автоматически предложит новые серверы при покупке
2. ✅ Пользователи смогут выбирать между 4 активными серверами:
   - 🇫🇷 Франция
   - 🇺🇸 США 1 (новый)
   - 🇬🇧 Великобритания
   - 🇺🇸 США 2 (новый)
3. ✅ Load balancing будет работать автоматически

---

**Готово к деплою! 🚀**
