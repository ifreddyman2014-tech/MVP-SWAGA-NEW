# ✅ Исправление "Быстрое подключение"

## 🔍 Проблема
При нажатии "Быстрое подключение" не отображаются серверы.

## ✨ Что было исправлено

### 1. Добавлена загрузка серверов при старте бота
**Файл:** `bot.py`, функция `on_startup()`

Теперь при запуске бота автоматически загружаются все серверы из `servers.json` и выводится информация в лог:
```python
# Загрузка конфигурации серверов
from servers import server_manager
if server_manager.load_config():
    logger.info("Конфигурация серверов загружена: %d серверов", len(server_manager.servers))
    for srv_id, srv in server_manager.servers.items():
        status = "✅" if srv.enabled else "❌"
        logger.info("  %s %s (%s)", status, srv.name, srv_id)
else:
    logger.error("❌ Не удалось загрузить конфигурацию серверов!")
```

## 📋 Что нужно сделать

### Шаг 1: Проверить серверы
Запустите тест загрузки серверов:
```bash
python3 test_servers_load.py
```

Вы должны увидеть:
```
✅ Включенных серверов: 4
  - Финляндия (основной) (fi1)
  - Германия (de1)
  - Латвия (lv1)
  - Нидерланды (nl1)
```

### Шаг 2: Настроить .env

**Обязательные переменные:**

```bash
# Токен бота (получить у @BotFather)
BOT_TOKEN=your_bot_token_here

# Ваш Telegram ID (для админки)
ADMIN_IDS=your_telegram_id

# База данных (SQLite - по умолчанию)
DATABASE_PATH=./vpn_bot.db

# URL для подписок (куда будет вести кнопка)
# Для локального теста:
SUB_BASE_URL=http://127.0.0.1:8888/sub/
# Для продакшн:
# SUB_BASE_URL=https://your-domain.com/sub/

# Порт для сервера подписок
SUB_LISTEN_PORT=8888
```

**Дефолтные настройки 3X-UI** (если не используете мультисервер):
```bash
XUI_HOST=150.241.77.138
XUI_PORT=2055
XUI_WEB_PATH=/JXmOAqpCBtH14wRJ2t
XUI_USERNAME=r03-jywLYr
XUI_PASSWORD=881NdAr-wBhhWN
INBOUND_ID=1
```

**VPN настройки** (из servers.json - Германия):
```bash
VPN_HOST=150.241.77.138
VPN_PORT=19571
VPN_TRANSPORT=tcp
REALITY_PUBLIC_KEY=9J1AXF06NYExtH0siVBABHH7IQcnzLMZOWgJIJ4_QA4
REALITY_SHORT_ID=d425791dd44d31
REALITY_SNI=web.de
REALITY_FINGERPRINT=chrome
```

### Шаг 3: Запустить бота

```bash
python3 bot.py
```

**Проверьте логи** при запуске:
```
[INFO] База данных инициализирована
[INFO] Конфигурация серверов загружена: 4 серверов
[INFO]   ✅ Финляндия (основной) (fi1)
[INFO]   ✅ Германия (de1)
[INFO]   ✅ Латвия (lv1)
[INFO]   ✅ Нидерланды (nl1)
[INFO] YooKassa callback установлен
[INFO] Команды бота установлены
[INFO] Subscription server started on 127.0.0.1:8888  <-- ВАЖНО!
[INFO] Фоновые задачи запущены
```

### Шаг 4: Протестировать

1. Откройте бота в Telegram
2. Напишите `/start`
3. Нажмите "Личный кабинет"
4. Нажмите "⚡ Быстрое подключение"

**Что должно произойти:**
- Откроется страница с конфигурацией VPN
- **Будут показаны все 4 сервера** из `servers.json`:
  - 🇫🇮 SWAGA Финляндия (основной)
  - 🇩🇪 SWAGA Германия
  - 🇱🇻 SWAGA Латвия
  - 🇳🇱 SWAGA Нидерланды

## 🐛 Отладка

### Проблема: "Subscription server not started"
**Решение:** Убедитесь, что:
- Порт 8888 свободен: `lsof -i :8888`
- В .env установлен `SUB_LISTEN_PORT=8888`

### Проблема: "No enabled servers found"
**Решение:**
- Запустите `python3 test_servers_load.py`
- Проверьте, что `enabled: true` в `servers.json`

### Проблема: "Показывается только 1 сервер"
**Решение:**
- Это нормально, если в `sub_app.py` включен fallback на дефолтный сервер
- Проверьте, что `server_manager.servers` не пустой
- Добавьте debug лог в `sub_app.py` строка 96:
```python
enabled_servers = [s for s in server_manager.get_all_servers() if s.enabled]
logger.info(f"DEBUG: enabled_servers count = {len(enabled_servers)}")
```

## ✅ Готово!

Теперь при запуске бота серверы будут загружаться автоматически, и кнопка "Быстрое подключение" будет показывать все доступные серверы.

## 📁 Измененные файлы
- ✅ `bot.py` - добавлена загрузка серверов в `on_startup()`
- ✅ `test_servers_load.py` - новый файл для тестирования
- ✅ `FIX_QUICK_CONNECT.md` - эта инструкция

## 🚀 Следующие шаги

После успешного запуска:
1. Настройте продакшн домен в `SUB_BASE_URL`
2. Настройте HTTPS (nginx + certbot)
3. Настройте автозапуск через systemd:
   ```bash
   sudo systemctl enable swaga-bot
   sudo systemctl start swaga-bot
   ```

---

**Если проблемы остались** - проверьте логи бота и напишите, что именно не работает! 📝
