# Subscription Server — Техническое задание

## Проблема

Сейчас бот отправляет пользователю **одиночный VLESS-конфиг**:
```
v2raytun://install-config?url={vless_link}&name=SWAGA
```

Это **не подписка** — это разовый импорт одного ключа.

**Последствия:**
- V2RayTun не показывает название бота (@Swaga_vpnbot) под подпиской
- При добавлении нового сервера пользователь **не получает ключ автоматически** — нужно вручную зайти в бота
- Нет красивой страницы как у VyperNet (sub.vypernet.cc/token)
- Нет трекинга трафика и статуса прямо в приложении

**VyperNet делает правильно:**
```
v2raytun://import/https://sub.vypernet.cc/{token}
```
Это URL подписки — приложение само обновляет список серверов и показывает профиль.

---

## Решение: Subscription Server

Добавить HTTP-эндпоинты в FastAPI (main.py), которые обслуживают подписки.

### Архитектура

```
Пользователь
    │
    ├── /connect/{sub_token}    ← HTML страница (браузер)
    │       └── кнопка "Добавить подписку" → v2raytun://import/{sub_url}
    │
    └── /sub/{sub_token}        ← Subscription endpoint (V2RayTun, Happ, и др.)
            ├── Headers: profile-title, profile-web-page-url, ...
            └── Body: base64(vless://...\nvless://...\n...)
```

---

## Изменения в коде

### 1. models.py — добавить `sub_token` в Subscription

```python
# В класс Subscription добавить поле:
sub_token: Mapped[str] = mapped_column(
    String(36),
    unique=True,
    nullable=False,
    default=lambda: str(uuid4()),
    index=True,
)
```

**Зачем:** публичный UUID для доступа к подписке без раскрытия внутреннего `id`.

### 2. migrations.py — добавить миграцию

```python
# Добавить колонку sub_token к существующим подпискам
ALTER TABLE subscriptions ADD COLUMN sub_token VARCHAR(36) UNIQUE;
UPDATE subscriptions SET sub_token = gen_random_uuid()::text WHERE sub_token IS NULL;
ALTER TABLE subscriptions ALTER COLUMN sub_token SET NOT NULL;
```

### 3. main.py — добавить эндпоинты

#### 3a. GET /sub/{sub_token} — сырая подписка для приложений

```python
@app.get("/sub/{sub_token}")
async def subscription_feed(sub_token: str, session: AsyncSession = Depends(get_db_session)):
    """
    Subscription endpoint for V2RayTun, Happ, FlClashX, etc.

    Returns base64-encoded list of VLESS links with profile headers.
    V2RayTun shows profile-web-page-url as a clickable link under the subscription.
    """
    # 1. Найти подписку по sub_token
    # 2. Проверить что подписка активна
    # 3. Получить все ключи (Key) + серверы (Server) для этой подписки
    # 4. Сгенерировать VLESS-ссылки
    # 5. base64 encode
    # 6. Вернуть Response с заголовками:

    headers = {
        "profile-title": "SWAGA VPN",
        "profile-web-page-url": "https://t.me/Swaga_vpnbot",
        "profile-update-interval": "12",
        "content-disposition": 'attachment; filename="SWAGA-VPN"',
        "subscription-userinfo": f"upload=0; download={used_bytes}; total={total_bytes}; expire={expire_ts}",
    }
    return Response(
        content=base64.b64encode(vless_links_joined.encode()).decode(),
        media_type="text/plain",
        headers=headers,
    )
```

#### 3b. GET /connect/{sub_token} — веб-страница

```python
@app.get("/connect/{sub_token}")
async def connect_page(sub_token: str, session: AsyncSession = Depends(get_db_session)):
    """
    Web page for end users. Shows subscription info + install instructions.
    Similar to sub.vypernet.cc/{token}
    """
    # Вернуть HTMLResponse с:
    # - Логотип SWAGA VPN
    # - Статус подписки (активна/истекла)
    # - Дата истечения, трафик
    # - Кнопки: "Скачать V2RayTun", "Добавить подписку"
    # - Ссылка на Telegram бот
    # - Инструкция для iOS/Android/Windows
```

**Sub URL для кнопки "Добавить подписку":**
```
v2raytun://import/{webhook_base_url}/sub/{sub_token}
```

### 4. user.py — изменить тип deeplink

Изменить функцию `build_v2raytun_deeplink`:

```python
# БЫЛО:
def build_v2raytun_deeplink(vless_url: str) -> str:
    encoded = urllib.parse.quote(vless_url, safe="")
    return f"v2raytun://install-config?url={encoded}&name=SWAGA"

# СТАЛО:
def build_subscription_deeplink(sub_url: str) -> str:
    encoded = urllib.parse.quote(sub_url, safe="")
    return f"v2raytun://import/{encoded}"
```

И везде где вызывается `build_v2raytun_deeplink(vless_links[0])` — заменить на:
```python
sub_url = f"{settings.webhook_base_url}/sub/{subscription.sub_token}"
deeplink = build_subscription_deeplink(sub_url)
```

### 5. config.py — добавить бота username

```python
bot_username: str = Field("Swaga_vpnbot", description="Bot username for profile-web-page-url")
```

---

## HTML страница /connect/{token}

Минимальная структура (inline CSS, без зависимостей):

```html
<!DOCTYPE html>
<html>
<head>
  <title>SWAGA VPN</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <!-- Шапка с логотипом -->
  <header>SWAGA VPN + иконка Telegram → t.me/Swaga_vpnbot</header>

  <!-- Карточка пользователя -->
  <div class="card">
    Имя пользователя: {username}
    Статус: Активна ✓
    Истекает: {expiry_date}
    Трафик: {used} / {total}
  </div>

  <!-- Блок установки -->
  <section>
    <h2>Установка</h2>

    <!-- Кнопки приложений -->
    [V2RayTun] [Happ] [FlClash]

    <!-- Кнопка добавления подписки -->
    <a href="v2raytun://import/{sub_url}">+ Добавить подписку</a>

    <!-- Ручная ссылка -->
    <button onclick="copy('{sub_url}')">Скопировать ссылку</button>
  </section>
</body>
</html>
```

---

## Порядок реализации

| # | Задача | Файл | Сложность |
|---|--------|------|-----------|
| 1 | Добавить `sub_token` в Subscription | models.py | Низкая |
| 2 | Написать миграцию для existing записей | migrations.py | Низкая |
| 3 | Эндпоинт `/sub/{token}` с base64 + headers | main.py | Средняя |
| 4 | Эндпоинт `/connect/{token}` с HTML | main.py | Средняя |
| 5 | Заменить deeplink на subscription URL | user.py | Низкая |
| 6 | Добавить `bot_username` в config | config.py | Низкая |
| 7 | Тест: добавить подписку в V2RayTun, проверить `@Swaga_vpnbot` | — | — |

---

## Ожидаемый результат

После реализации:

1. Бот отправляет ссылку `v2raytun://import/https://sub.swaga-vpn.ru/sub/{token}`
2. V2RayTun добавляет **подписку** (не конфиг), периодически обновляет её
3. Под подпиской в приложении видна синяя ссылка **@Swaga_vpnbot**
4. При открытии `https://sub.swaga-vpn.ru/connect/{token}` в браузере — красивая страница
5. При добавлении нового сервера — все пользователи **автоматически** получат новый ключ при следующем обновлении подписки

---

## Зависимости

- Нет новых pip-пакетов (base64, htmlResponse — уже в стандартной библиотеке и FastAPI)
- Нужен публичный домен для sub_url (уже есть: `webhook_base_url` из .env)
- Если `webhook_base_url` = `https://sub.swaga-vpn.ru`, то sub URL будет: `https://sub.swaga-vpn.ru/sub/{token}`
