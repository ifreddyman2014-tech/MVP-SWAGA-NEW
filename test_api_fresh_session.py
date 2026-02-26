#!/usr/bin/env python3
"""
Тест API с созданием новой сессии для каждого запроса.
"""
import asyncio
import aiohttp
import json
from datetime import datetime, timedelta

async def test_with_fresh_sessions():
    """Тест с новой сессией для каждого запроса."""

    base_url = "https://80.76.49.140:61753/8J0lp7fw3i0SRtKAp6"
    username = "FkrcdX0yCG"
    password = "IOBwHAvUm6D7LiwOTz"

    print("="*80)
    print("🧪 ТЕСТ С НОВОЙ СЕССИЕЙ ДЛЯ КАЖДОГО ЗАПРОСА")
    print("="*80)

    # Шаг 1: Логин и получение cookie
    print("\n1️⃣ Логин...")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(
        connector=connector,
        cookie_jar=aiohttp.CookieJar(unsafe=True)
    ) as session:
        login_url = f"{base_url}/login"
        async with session.post(
            login_url,
            json={"username": username, "password": password}
        ) as resp:
            data = await resp.json()
            print(f"   Response: {data}")

            if not data.get("success"):
                print("❌ Логин не удался!")
                return

            # Сохраняем cookies
            cookies = session.cookie_jar.filter_cookies(login_url)
            print(f"   ✅ Логин успешен! Cookies: {len(cookies)}")

            # Пробуем получить список inbound'ов в той же сессии
            print("\n2️⃣ Список inbound'ов (та же сессия)...")
            test_endpoints = [
                "/panel/inbound/list",
                "/xui/inbound/list",
                "/panel/api/inbounds/list",
            ]

            for endpoint in test_endpoints:
                url = f"{base_url}{endpoint}"
                try:
                    print(f"   Пробуем {endpoint}...")
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                        print(f"      Status: {resp.status}")
                        if resp.status == 200:
                            try:
                                data = json.loads(text)
                                if data.get("success"):
                                    print(f"      ✅ Работает! Данные: {text[:100]}")
                                    return
                                else:
                                    print(f"      ⚠️ Success=false: {data.get('msg')}")
                            except:
                                print(f"      ⚠️ Не JSON: {text[:100]}")
                        else:
                            print(f"      ❌ HTTP {resp.status}")
                except Exception as e:
                    print(f"      ❌ Ошибка: {type(e).__name__}: {e}")

    # Шаг 2: Новая сессия с cookies
    print("\n3️⃣ Попытка с новой сессией но теми же cookies...")
    connector = aiohttp.TCPConnector(ssl=False)
    cookie_jar = aiohttp.CookieJar(unsafe=True)

    # Попробуем установить cookie вручную
    async with aiohttp.ClientSession(
        connector=connector,
        cookie_jar=cookie_jar
    ) as session:
        # Сначала логин чтобы получить cookie
        async with session.post(
            f"{base_url}/login",
            json={"username": username, "password": password}
        ) as resp:
            await resp.json()

        # Теперь пробуем запрос
        print("   Пробуем /panel/inbound/list...")
        try:
            async with session.get(
                f"{base_url}/panel/inbound/list",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                text = await resp.text()
                print(f"   Status: {resp.status}")
                print(f"   Response: {text[:200]}")
        except Exception as e:
            print(f"   ❌ Ошибка: {type(e).__name__}: {e}")

    print("\n" + "="*80)
    print("🏁 ТЕСТ ЗАВЕРШЕН")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(test_with_fresh_sessions())
