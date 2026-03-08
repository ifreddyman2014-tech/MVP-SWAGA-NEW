# SWAGA VPN — Android App

Нативное Android приложение на **Kotlin + Jetpack Compose**.

## Архитектура

```
android/
├── app/src/main/kotlin/com/swaga/vpn/
│   ├── SwagaApp.kt            — Application class, инициализация
│   ├── MainActivity.kt        — Единственная Activity, запрос VPN permission
│   ├── ui/
│   │   ├── SwagaNavHost.kt    — Navigation: Splash → Auth → Home
│   │   ├── theme/             — Цвета, типографика (тёмная тема)
│   │   └── screens/
│   │       ├── SplashScreen.kt   — Проверка токена при старте
│   │       ├── AuthScreen.kt     — Ввод URL подписки / токена
│   │       └── HomeScreen.kt     — Статус, кнопка Connect, список серверов
│   ├── data/
│   │   ├── AppPreferences.kt  — DataStore: sub_token, sub_base_url
│   │   └── SubscriptionInfo.kt
│   ├── api/
│   │   └── SwagaApiClient.kt  — Fetch /sub/{token}, parse base64 + headers
│   └── vpn/
│       ├── VpnState.kt        — DISCONNECTED / CONNECTING / CONNECTED / ERROR
│       ├── VpnController.kt   — Singleton: connect/disconnect, публикует состояние
│       ├── SwagaVpnService.kt — Android VpnService, TUN interface
│       └── xray/
│           ├── XrayConfig.kt  — VLESS URL → xray JSON config
│           └── XrayRunner.kt  — Запуск/остановка xray-core (stub → реальный AAR)
```

## Технологии

| Слой | Библиотека |
|------|-----------|
| UI | Jetpack Compose + Material3 |
| Navigation | Navigation Compose |
| State | StateFlow + collectAsState |
| Storage | DataStore Preferences |
| HTTP | OkHttp |
| VPN engine | xray-core (libxray.aar) |

## Сборка

```bash
cd android
./gradlew assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

## Подключение xray-core (обязательно перед релизом)

1. Скачать `libxray.aar` с https://github.com/xtls/libxray/releases
2. Положить в `android/app/libs/libxray.aar`
3. В `app/build.gradle.kts` раскомментировать строку с `fileTree("libs")`
4. В `XrayRunner.kt` заменить stub на реальные вызовы:
   ```kotlin
   import libxray.Libxray
   Libxray.runXray(configJson)   // start
   Libxray.stopXray()            // stop
   ```

## Экраны

### SplashScreen
- Проверяет наличие сохранённого токена
- Перенаправляет на Auth или Home

### AuthScreen
- Принимает полный URL подписки: `https://sub.swaga-vpn.ru/sub/UUID`
- Или голый UUID токен
- Проверяет подписку через API, сохраняет токен

### HomeScreen
- Карточка подписки: статус, дата истечения, кол-во серверов
- Большая кнопка Connect (анимированная, меняет цвет)
- Список серверов из подписки
- Кнопка обновления подписки
- Кнопка выхода
