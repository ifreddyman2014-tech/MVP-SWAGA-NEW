# Руководство по добавлению новых серверов

## Обзор

SWAGA VPN Bot поддерживает мультисерверную архитектуру. При создании подписки или пробного периода **автоматически создаются ключи на всех активных серверах**. Пользователь получает доступ ко всем серверам одновременно.

## Преимущества мультисерверной архитектуры

✅ **Отказоустойчивость** - если один сервер недоступен, пользователь использует другой
✅ **Балансировка нагрузки** - пользователи распределяются между серверами
✅ **Гибкость выбора** - пользователь может выбрать сервер с лучшей скоростью
✅ **Бесшовная миграция** - UUID клиента едины на всех серверах

## Процесс добавления нового сервера

### Этап 1: Настройка сервера

Следуйте инструкциям из `NEW_SERVER_SETUP.md`:

```bash
# 1. Установите 3X-UI
./setup_finland_server.sh root@new-server-ip

# 2. Настройте файрвол
ufw allow 334/tcp    # 3X-UI panel
ufw allow 18971/tcp  # VPN port

# 3. Создайте VLESS Inbound с Reality + XHTTP
# (см. NEW_SERVER_SETUP.md шаг 3)

# 4. Получите Reality параметры
# Public Key, Short IDs, и т.д.
```

### Этап 2: Добавление в servers.json

Добавьте новый сервер в `servers.json`:

```json
{
  "servers": [
    {
      "id": "fi1",
      "name": "Финляндия (основной)",
      "host": "144.31.132.116",
      "xui_host": "144.31.132.116",
      "xui_port": 334,
      "xui_web_path": "/b07En1ZZsNtdTXo426",
      "xui_username": "lE2W3NXLFK",
      "xui_password": "gtxPfyk2ie",
      "vpn_port": 18971,
      "inbound_id": 1,
      "max_users": 200,
      "priority": 15,
      "enabled": true,
      "location": "FI",
      "transport": "xhttp",
      "transport_path": "/adv",
      "transport_host": "yandex.ru",
      "xhttp_mode": "packet-up",
      "reality_pbk": "8oddnDvmMx3vAGXqGyhRkl2gG1QmbAiOmWCwTamXjRM",
      "reality_sid": "f8999e",
      "reality_sni": "www.lomarengas.fi",
      "reality_fp": "chrome"
    }
  ]
}
```

#### Параметры конфигурации

| Параметр | Описание | Пример |
|----------|----------|--------|
| **id** | Уникальный ID сервера | `"fi1"` |
| **name** | Отображаемое название | `"Финляндия (основной)"` |
| **host** | IP/домен для подключения клиентов | `"144.31.132.116"` |
| **xui_host** | IP для 3X-UI API | `"144.31.132.116"` |
| **xui_port** | Порт 3X-UI панели | `334` |
| **xui_web_path** | Web path панели | `"/b07En1ZZsNtdTXo426"` |
| **xui_username** | Логин панели | `"lE2W3NXLFK"` |
| **xui_password** | Пароль панели | `"gtxPfyk2ie"` |
| **vpn_port** | Порт VPN | `18971` |
| **inbound_id** | ID inbound в панели | `1` |
| **max_users** | Максимум пользователей | `200` |
| **priority** | Приоритет (выше = предпочтительнее) | `15` |
| **enabled** | Включён ли сервер | `true` |
| **location** | Код страны (ISO 3166-1 alpha-2) | `"FI"` |
| **transport** | Транспорт (tcp/xhttp/ws) | `"xhttp"` |
| **transport_path** | Путь для xhttp/ws | `"/adv"` |
| **transport_host** | Host header | `"yandex.ru"` |
| **xhttp_mode** | Режим xhttp | `"packet-up"` |
| **reality_pbk** | Reality Public Key | `"8oddnDvmMx..."` |
| **reality_sid** | Reality Short ID | `"f8999e"` |
| **reality_sni** | Reality SNI (домен маскировки) | `"www.lomarengas.fi"` |
| **reality_fp** | Reality Fingerprint | `"chrome"` |

### Этап 3: Синхронизация с базой данных

После добавления сервера в `servers.json`, синхронизируйте с БД:

```bash
# 1. Проверьте изменения (dry-run)
python sync_servers.py --dry-run

# 2. Примените изменения
python sync_servers.py

# 3. Проверьте что сервер добавлен
python sync_servers.py --list
```

**Вывод:**
```
=============================================================
SWAGA VPN - Server Synchronization
=============================================================

Processing: Финляндия (основной) (fi1)
  Creating new server: Финляндия (основной)
    Host: 144.31.132.116
    Port: 18971
    API: https://144.31.132.116:334/b07En1ZZsNtdTXo426
    Transport: xhttp
    Reality SNI: www.lomarengas.fi
  ✓ Created server: Финляндия (основной) (DB ID: 1)

=============================================================
SYNCHRONIZATION SUMMARY
=============================================================
Created: 1
Updated: 0
Unchanged: 2
Errors: 0
```

### Этап 4: Перезапуск бота

```bash
# На сервере с ботом
cd /root/MVP-SWAGA-NEW

# Обновить код
git pull origin master  # или ваша основная ветка

# Перезапустить
systemctl restart vpn-bot
# или
pm2 restart vpn-bot
# или
docker-compose restart
```

### Этап 5: Проверка

```bash
# 1. Проверьте логи бота
tail -f /var/log/vpn-bot.log

# 2. В Telegram:
#    - Отправьте /start
#    - Активируйте пробный период
#    - Нажмите "🚀 Получить доступ"
#    - Проверьте что отображаются все серверы

# 3. Проверьте что ключи созданы в 3X-UI панели нового сервера
```

## Управление серверами

### Временное отключение сервера

```json
{
  "id": "de1",
  "name": "Германия",
  "enabled": false,  // Отключить сервер
  ...
}
```

```bash
python sync_servers.py
```

Новые пользователи **не будут** получать ключи на этом сервере.
Существующие пользователи **сохранят** свои ключи.

### Изменение приоритета

```json
{
  "id": "fi1",
  "priority": 20,  // Высокий приоритет
  ...
},
{
  "id": "de1",
  "priority": 5,   // Низкий приоритет
  ...
}
```

Приоритет влияет на:
- Порядок отображения в списке
- Выбор сервера при балансировке нагрузки (если будет реализовано)

### Удаление сервера

⚠️ **ВНИМАНИЕ:** Удаление сервера из `servers.json` НЕ удаляет его из БД автоматически!

Порядок безопасного удаления:

1. **Мигрируйте клиентов** на другой сервер:
   ```bash
   python migrate_clients.py --from de1 --to fi1
   ```

2. **Отключите сервер** в `servers.json`:
   ```json
   {
     "id": "de1",
     "enabled": false,
     ...
   }
   ```

3. **Синхронизируйте с БД**:
   ```bash
   python sync_servers.py
   ```

4. **Через неделю** удалите из `servers.json` и снова синхронизируйте

5. **Вручную удалите из БД** (опционально):
   ```sql
   DELETE FROM servers WHERE name = 'Германия';
   ```

## Примеры

### Пример 1: Добавление второго Finland сервера

```json
{
  "id": "fi2",
  "name": "Финляндия 2",
  "host": "185.xx.xx.xx",
  "xui_host": "185.xx.xx.xx",
  "xui_port": 334,
  "xui_web_path": "/random-path-123",
  "xui_username": "admin",
  "xui_password": "secure-password",
  "vpn_port": 443,
  "inbound_id": 1,
  "max_users": 300,
  "priority": 14,
  "enabled": true,
  "location": "FI",
  "transport": "xhttp",
  "transport_path": "/adv",
  "transport_host": "yandex.ru",
  "xhttp_mode": "packet-up",
  "reality_pbk": "...",
  "reality_sid": "...",
  "reality_sni": "www.example.fi",
  "reality_fp": "chrome"
}
```

```bash
python sync_servers.py
systemctl restart vpn-bot
```

### Пример 2: Добавление US сервера

```json
{
  "id": "us1",
  "name": "США (Нью-Йорк)",
  "host": "us-ny.example.com",
  "xui_host": "104.xx.xx.xx",
  "xui_port": 2053,
  "xui_web_path": "/",
  "xui_username": "admin",
  "xui_password": "password",
  "vpn_port": 443,
  "inbound_id": 1,
  "max_users": 150,
  "priority": 8,
  "enabled": true,
  "location": "US",
  "transport": "xhttp",
  "transport_path": "/api/v1",
  "transport_host": "cloudflare.com",
  "xhttp_mode": "packet-up",
  "reality_pbk": "...",
  "reality_sid": "...",
  "reality_sni": "www.microsoft.com",
  "reality_fp": "chrome"
}
```

## Часто задаваемые вопросы

**Q: Нужно ли создавать ключи на новом сервере для существующих пользователей?**
A: Нет, это произойдет автоматически при следующем обновлении подписки или при запросе ключей.

**Q: Как проверить что ключи созданы на новом сервере?**
A: Откройте 3X-UI панель → Inbounds → View Clients. Должны быть клиенты с email `user-{telegram_id}`.

**Q: Что если у сервера другой Reality Public Key?**
A: Каждый сервер имеет свой набор Reality ключей. Это нормально и безопасно.

**Q: Можно ли использовать разные транспорты на разных серверах?**
A: Да! Один сервер может использовать xhttp, другой - ws, третий - tcp. Всё настраивается в servers.json.

**Q: Как узнать Reality параметры сервера?**
A:
1. Откройте 3X-UI панель
2. Inbounds → Edit (иконка карандаша)
3. Reality settings → Public Key, Short IDs
4. Или используйте команду на сервере:
   ```bash
   xray x25519
   ```

**Q: Влияет ли priority на что-то кроме отображения?**
A: В текущей версии - только на порядок отображения. Балансировка по приоритету может быть добавлена позже.

**Q: Можно ли добавить сервер без перезапуска бота?**
A: Нет, после `sync_servers.py` требуется перезапуск бота.

## Мониторинг серверов

Проверка здоровья серверов (TODO - будет добавлено):

```bash
# Проверить доступность всех серверов
python check_servers.py

# Вывод:
# ✓ Финляндия (основной) - OK
# ✓ Германия - OK
# ✗ Латвия - ERROR: Connection timeout
```

## Troubleshooting

### Ошибка: "Failed to sync key to server"

Проверьте:
1. **Доступность панели**: `curl -k https://server-ip:port/web-path/login`
2. **Учетные данные**: `xui_username`, `xui_password`
3. **Inbound ID**: правильный ли `inbound_id` в конфигурации
4. **Файрвол**: открыт ли порт панели

### Ошибка: "No active servers found"

```bash
# Проверьте что серверы в БД
python sync_servers.py --list

# Если пусто, синхронизируйте
python sync_servers.py
```

### Пользователь видит не все серверы

1. Проверьте что серверы `enabled: true` в servers.json
2. Проверьте что серверы `is_active: true` в БД
3. Перезапустите бота
4. Пользователь должен запросить ключи заново (/start → Получить доступ)

---

**Дата создания:** 2026-02-16
**Версия:** 1.0
