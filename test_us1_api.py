#!/usr/bin/env python3
"""
Тестовый скрипт для проверки API us1 сервера.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.services.xui import ThreeXUIClient

async def test_us1():
    """Тест API us1 сервера."""

    base_url = "https://80.76.49.140:61753/8J0lp7fw3i0SRtKAp6"
    username = "FkrcdX0yCG"
    password = "IOBwHAvUm6D7LiwOTz"

    print("="*80)
    print("🧪 ТЕСТ API US1 СЕРВЕРА")
    print("="*80)
    print(f"URL: {base_url}")
    print()

    client = ThreeXUIClient(
        base_url=base_url,
        username=username,
        password=password,
        inbound_id=1,
        verify_ssl=False
    )

    try:
        async with client.session():
            print("✅ Авторизация успешна!\n")

            # Тест 1: Список inbound'ов
            print("📋 Тест 1: Получение списка inbound'ов...")
            try:
                inbounds = await client.list_inbounds()
                print(f"   ✅ Успех! Найдено inbound'ов: {len(inbounds)}")
                for ib in inbounds:
                    print(f"      - ID: {ib.get('id')}, Remark: {ib.get('remark')}, Protocol: {ib.get('protocol')}")
            except Exception as e:
                print(f"   ❌ Ошибка: {e}")

            # Тест 2: Получение конкретного inbound
            print("\n📋 Тест 2: Получение inbound #1...")
            try:
                inbound = await client.get_inbound(1)
                print(f"   ✅ Успех! Inbound: {inbound.get('remark', 'N/A')}")
            except Exception as e:
                print(f"   ❌ Ошибка: {e}")

            # Тест 3: Список клиентов
            print("\n👥 Тест 3: Получение списка клиентов inbound #1...")
            try:
                clients = await client.list_clients(1)
                print(f"   ✅ Успех! Найдено клиентов: {len(clients)}")
                for c in clients[:3]:  # Показать первых 3
                    print(f"      - Email: {c.get('email')}, UUID: {c.get('id', '')[:8]}...")
            except Exception as e:
                print(f"   ❌ Ошибка: {e}")

            # Тест 4: Добавление тестового клиента
            print("\n➕ Тест 4: Добавление тестового клиента...")
            test_uuid = "00000000-0000-0000-0000-000000000001"
            test_email = "test_api_check_12345"
            test_expiry = int((datetime.now() + timedelta(days=1)).timestamp() * 1000)

            try:
                await client.add_client(
                    uuid=test_uuid,
                    email=test_email,
                    expiry_ms=test_expiry,
                    inbound_id=1,
                    flow="xtls-rprx-vision"
                )
                print(f"   ✅ Успех! Тестовый клиент добавлен")

                # Удалим тестового клиента
                print("   🗑️  Удаление тестового клиента...")
                try:
                    await client.delete_client(test_uuid, 1)
                    print("   ✅ Тестовый клиент удален")
                except Exception as e:
                    print(f"   ⚠️  Не удалось удалить: {e}")

            except Exception as e:
                print(f"   ❌ Ошибка: {e}")

    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()

    print("\n" + "="*80)
    print("🏁 ТЕСТ ЗАВЕРШЕН")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(test_us1())
