# Инструкция по настройке нового VPN сервера

## Информация о сервере

* **Тарифный план**: FI-RZ-1
* **Дата открытия**: 2026-02-16
* **Доменное имя**: vm1484131.vds.chsl.one
* **IP-адрес**: 144.31.132.116
* **Пользователь**: root
* **Пароль**: 14GJ6H096A6d

## Этап 1: Автоматическая установка 3X-UI

### Вариант A: Автоматический деплой (рекомендуется)

```bash
# Сделать скрипты исполняемыми
chmod +x setup-new-server.sh deploy-to-new-server.sh

# Запустить автоматическую установку
./deploy-to-new-server.sh
```

Скрипт автоматически:
- Подключится к серверу
- Обновит систему
- Установит 3X-UI панель (MHSanaei fork)
- Настроит файрвол (UFW)
- Сгенерирует Reality ключи
- Создаст конфигурационный файл с всеми параметрами

### Вариант B: Ручная установка

```bash
# Подключиться к серверу
ssh root@144.31.132.116

# Скопировать скрипт и запустить
curl -O https://raw.githubusercontent.com/your-repo/MVP-SWAGA-NEW/main/setup-new-server.sh
chmod +x setup-new-server.sh
./setup-new-server.sh
```

## Этап 2: Получение параметров конфигурации

После установки подключитесь к серверу и просмотрите сгенерированную конфигурацию:

```bash
ssh root@144.31.132.116
cat /root/server-config.txt
```

Вы получите:
- URL панели 3X-UI
- Логин и пароль администратора
- Reality Public Key
- Reality Private Key
- Reality Short ID
- Порты и другие параметры

**ВАЖНО**: Сохраните эти данные в надежном месте!

## Этап 3: Настройка VLESS Inbound в панели 3X-UI

1. **Войдите в панель 3X-UI**
   - Откройте URL из `server-config.txt` в браузере
   - Введите логин и пароль
   - Пример: `http://144.31.132.116:2053/a1b2c3d4e5f6`

2. **Создайте новый Inbound**
   - Перейдите в раздел "Inbounds"
   - Нажмите "Add Inbound"

3. **Настройте параметры Inbound**

   **Основные настройки:**
   - Remark: `SWAGA-FI-Main`
   - Protocol: `VLESS`
   - Listen IP: `0.0.0.0` или оставьте пустым
   - Port: `19571`
   - Total Traffic: оставьте пустым (unlimited)
   - Client Expiry Time: оставьте пустым

   **Security Settings:**
   - Security: `Reality`
   - TLS Flow: `xtls-rprx-vision`
   - UTLS: `chrome` (fingerprint)
   - Dest (Server Name): `yandex.ru:443` или `www.microsoft.com:443`
   - Server Names (SNI): `yandex.ru` или `www.microsoft.com`
   - Private Key: *вставьте Reality Private Key из server-config.txt*
   - Short IDs: *вставьте Reality Short ID из server-config.txt*
   - Public Key: отобразится автоматически

   **Transport Settings:**
   - Network: `XHTTP` (или `HTTP/2` если нет XHTTP)
   - Path: `/adv`
   - Host: `yandex.ru`
   - Mode: `packet-up`

4. **Сохраните Inbound**
   - Нажмите "Create"
   - Запишите **Inbound ID** (виден в URL при редактировании)

5. **Проверка**
   - Убедитесь, что Inbound активен (зеленая галочка)
   - Проверьте, что порт 19571 открыт: `nc -zv 144.31.132.116 19571`

## Этап 4: Добавление сервера в servers.json

После получения всех параметров добавьте новый сервер в `servers.json`:

```json
{
  "id": "fi1",
  "name": "Финляндия (основной)",
  "host": "144.31.132.116",
  "xui_host": "144.31.132.116",
  "xui_port": 2053,
  "xui_web_path": "/ваш-web-path-из-server-config",
  "xui_username": "ваш-username-из-server-config",
  "xui_password": "ваш-password-из-server-config",
  "vpn_port": 19571,
  "inbound_id": 1,
  "max_users": 200,
  "priority": 15,
  "enabled": true,
  "location": "FI",
  "transport": "xhttp",
  "transport_path": "/adv",
  "transport_host": "yandex.ru",
  "xhttp_mode": "packet-up",
  "reality_pbk": "ваш-public-key-из-server-config",
  "reality_sid": "ваш-short-id-из-server-config",
  "reality_sni": "yandex.ru",
  "reality_fp": "chrome"
}
```

**Примечание**:
- Установите `priority: 15` (выше чем у текущего основного сервера DE с priority 10)
- Это сделает FI сервер основным

## Этап 5: Понижение приоритета старого основного сервера

В `servers.json` измените приоритет старого сервера DE:

```json
{
  "id": "de1",
  "name": "Германия",  // убрали "(основной)"
  "priority": 5,       // понизили с 10 до 5
  ...
}
```

## Этап 6: Тестирование

1. **Проверка подключения к 3X-UI API**
   ```bash
   # Из директории проекта
   python3 << EOF
   import requests
   import json

   xui_url = "http://144.31.132.116:2053"
   xui_path = "/ваш-web-path"
   username = "ваш-username"
   password = "ваш-password"

   # Логин
   response = requests.post(
       f"{xui_url}{xui_path}/login",
       data={"username": username, "password": password}
   )
   print("Login:", response.status_code)

   # Получение списка inbounds
   cookies = response.cookies
   inbounds = requests.get(f"{xui_url}{xui_path}/panel/api/inbounds/list", cookies=cookies)
   print("Inbounds:", inbounds.status_code)
   print(json.dumps(inbounds.json(), indent=2))
   EOF
   ```

2. **Создание тестового пользователя через бота**
   - Запустите бота
   - Активируйте пробный период
   - Проверьте, что клиент создан в панели 3X-UI

3. **Тестирование VPN подключения**
   - Используйте сгенерированную VLESS-ссылку
   - Подключитесь через клиент (V2RayNG, V2RayTUN)
   - Проверьте доступ к интернету

## Этап 7: Деплой изменений

```bash
# Проверить изменения
git status
git diff servers.json

# Создать коммит
git add servers.json NEW_SERVER_SETUP.md setup-new-server.sh deploy-to-new-server.sh
git commit -m "Add new Finland server (FI) as primary

- Added FI server (144.31.132.116) with priority 15
- Downgraded DE server priority from 10 to 5
- Added setup scripts for automated server installation
- Updated documentation"

# Запушить изменения
git push origin main
```

## Мониторинг и обслуживание

### Проверка статуса сервисов на сервере

```bash
ssh root@144.31.132.116

# Статус 3X-UI
systemctl status x-ui

# Логи 3X-UI
journalctl -u x-ui -f

# Проверка открытых портов
netstat -tulpn | grep -E '(2053|19571)'

# Использование ресурсов
top
df -h
```

### Бэкап конфигурации 3X-UI

```bash
ssh root@144.31.132.116

# Создать бэкап
mkdir -p /root/backups
tar -czf /root/backups/x-ui-backup-$(date +%Y%m%d).tar.gz \
    /usr/local/x-ui/ \
    /etc/x-ui/

# Скачать бэкап на локальный компьютер
scp root@144.31.132.116:/root/backups/x-ui-backup-*.tar.gz ./
```

### Обновление 3X-UI

```bash
ssh root@144.31.132.116

# Обновить до последней версии
bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)
```

## Устранение неполадок

### 3X-UI панель недоступна

```bash
# Проверить статус
systemctl status x-ui

# Перезапустить
systemctl restart x-ui

# Проверить логи
journalctl -u x-ui -n 100

# Проверить файрвол
ufw status
```

### VPN не подключается

1. Проверьте, что Inbound активен в панели
2. Проверьте, что порт 19571 открыт: `nc -zv 144.31.132.116 19571`
3. Проверьте Reality ключи (Public Key должен совпадать)
4. Проверьте SNI домен (должен быть доступен: `curl -I https://yandex.ru`)

### Бот не может создать клиента

1. Проверьте учетные данные 3X-UI в `.env`
2. Проверьте `inbound_id` (должен совпадать с ID в панели)
3. Проверьте логи бота: `docker-compose logs -f bot`
4. Проверьте доступность API: `curl http://144.31.132.116:2053/your-path/`

## Чеклист финальной проверки

- [ ] 3X-UI панель установлена и доступна
- [ ] VLESS Inbound создан и активен
- [ ] Reality ключи сгенерированы и настроены
- [ ] Порты 2053 и 19571 открыты в файрволе
- [ ] Сервер добавлен в servers.json с правильным приоритетом
- [ ] Тестовое подключение VPN успешно
- [ ] Бот может создавать клиентов через API
- [ ] Бэкап конфигурации создан
- [ ] Изменения закоммичены и запушены в git

---

**Готово!** Новый сервер настроен и готов к работе. 🚀
